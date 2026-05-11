"""Slack ETL.

Pulls Slack channel threads (and optionally DMs) via the Web API and
stores each thread as a Note in the workspace graph. Threads are the
natural unit of discussion — individual messages within a thread are
concatenated into the Note body.

Each thread Note:
  source      = "slack"
  path        = "<team_id>:<channel_id>:<thread_ts>"
  title       = first 80 chars of the root message text
  body        = concatenated "@author: message" lines
  modified_at = latest_reply ISO timestamp (or root ts if no replies)

Participants become Person nodes linked via `participated_in` edges
(role="thread_member"). Jira keys + GitHub PR refs in message text
produce `references_issue` / `references_pr` edges.

Edits and deletions are handled: `message_changed` subtype triggers a
re-upsert; `message_deleted` of a thread root deletes the Note.

Auth: Slack token from `auth_env` — either:
  - User token `xoxp-...` (can read DMs, all channels you're in)
  - Bot token  `xoxb-...` (only channels the bot is added to)

Rate limits: Slack Tier-2 methods (~20 req/min) are used for history
and replies. A lightweight `_throttle()` call respects `Retry-After`.

Settings (sources.yaml):
  channels:    []           channel IDs or names (e.g. "#eng-alerts", "C012ABC")
  include_dms: false        also fetch direct message threads
  since_days:  7            lookback window for initial / full sync
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from surrealdb import Surreal

from graph import builder
from library import sync_state
from graph.link_extractor import extract_jira_keys, extract_pr_refs

SOURCE_NAME = "slack"
SLACK_API = "https://slack.com/api"
PAGE_SIZE = 200
_LAST_REQUEST_TS: float = 0.0
_MIN_INTERVAL = 1.1  # seconds between calls (Tier-2 ~20 req/min)


@dataclass
class SyncStats:
    threads: int = 0
    deleted: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str) -> SyncStats:
    if not auth:
        raise ValueError("slack: SLACK_TOKEN is required (auth_env: SLACK_TOKEN)")

    channels_cfg = settings.get("channels") or []
    include_dms = bool(settings.get("include_dms", False))
    since_days = int(settings.get("since_days") or 7)
    full = bool(settings.get("full"))

    hdrs = {"Authorization": f"Bearer {auth}"}
    team_id = _get_team_id(hdrs)

    # Resolve channel names → IDs (batched, cached in-process)
    channel_ids = _resolve_channels(hdrs, channels_cfg)
    if include_dms:
        channel_ids.extend(_list_dm_channels(hdrs))

    if not channel_ids:
        print("[slack] no channels resolved — check settings.channels or add the bot to channels")
        return SyncStats()

    scope = ",".join(sorted(channel_ids))
    raw_cursor = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    # Slack ts is seconds.microseconds — compare as float; store as ISO for consistency
    oldest: str | None = None
    if raw_cursor:
        oldest = raw_cursor  # ISO string, converted to ts in the API call
    elif full or not raw_cursor:
        oldest = (
            datetime.now(tz=timezone.utc) - timedelta(days=since_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    started = sync_state.now_iso()

    # Users roster (email / display_name) fetched once per run
    users = _fetch_users(hdrs)

    stats = SyncStats()
    for ch_id in channel_ids:
        _sync_channel(db, hdrs, team_id, ch_id, oldest, users, stats)

    sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


# ---------- Channel sync ----------

def _sync_channel(
    db: Surreal, hdrs: dict, team_id: str, channel_id: str,
    oldest: str | None, users: dict[str, str], stats: SyncStats,
) -> None:
    oldest_ts = _iso_to_ts(oldest) if oldest else None

    for msg in _history(hdrs, channel_id, oldest_ts):
        subtype = msg.get("subtype") or ""
        thread_ts = msg.get("thread_ts") or msg.get("ts") or ""
        # Only process root messages (thread_ts == ts means root)
        if msg.get("ts") != thread_ts and not subtype:
            continue  # threaded reply — handled via _replies()

        if subtype == "message_deleted":
            builder.delete_note(db, SOURCE_NAME, f"{team_id}:{channel_id}:{thread_ts}")
            stats.deleted += 1
            continue

        # Full thread (root + replies)
        replies = []
        if int(msg.get("reply_count") or 0) > 0:
            replies = list(_replies(hdrs, channel_id, thread_ts))

        _ingest_thread(db, team_id, channel_id, thread_ts, msg, replies, users, stats)


# ---------- Thread → Note ----------

def _ingest_thread(
    db: Surreal, team_id: str, channel_id: str, thread_ts: str,
    root: dict, replies: list[dict], users: dict[str, str], stats: SyncStats,
) -> None:
    all_msgs = [root] + replies
    title = _plain(root.get("text") or "")[:80] or "(empty message)"
    body_lines: list[str] = []
    authors: set[str] = set()
    latest_ts = root.get("ts") or thread_ts

    for msg in all_msgs:
        uid = msg.get("user") or msg.get("bot_id") or ""
        name = users.get(uid) or uid or "unknown"
        text = _plain(msg.get("text") or "")
        body_lines.append(f"@{name}: {text}")
        if uid:
            authors.add(uid)
        if (msg.get("ts") or "") > latest_ts:
            latest_ts = msg["ts"]

    body = "\n".join(body_lines)
    modified_at = _ts_to_iso(latest_ts)
    path = f"{team_id}:{channel_id}:{thread_ts}"

    note_id = builder.upsert_note(
        db,
        source=SOURCE_NAME,
        path=path,
        title=title,
        body=body,
        modified_at=modified_at,
    )

    builder.link_note_references(db, note_id, body)

    for uid in authors:
        name = users.get(uid) or uid
        person_id = builder.upsert_person(db, name)
        builder.relate_participation(db, person_id, note_id, role="thread_member")

    stats.threads += 1


# ---------- Slack API helpers ----------

def _get_team_id(hdrs: dict) -> str:
    data = _call(hdrs, "auth.test")
    return data.get("team_id") or "T_unknown"


def _resolve_channels(hdrs: dict, names_or_ids: list[str]) -> list[str]:
    """Convert any '#name' entries to channel IDs; pass IDs through."""
    needs_resolution = [c for c in names_or_ids if not c.startswith("C")]
    if not needs_resolution:
        return [c.lstrip("#") for c in names_or_ids]

    name_map: dict[str, str] = {}
    cursor: str | None = None
    while True:
        params: dict = {"types": "public_channel,private_channel", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _call(hdrs, "conversations.list", params=params)
        for ch in data.get("channels") or []:
            name_map[ch["name"]] = ch["id"]
        next_cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not next_cursor:
            break
        cursor = next_cursor

    result: list[str] = []
    for entry in names_or_ids:
        clean = entry.lstrip("#")
        if clean.startswith("C"):
            result.append(clean)
        elif clean in name_map:
            result.append(name_map[clean])
        else:
            print(f"[slack] channel not found: {entry}")
    return result


def _list_dm_channels(hdrs: dict) -> list[str]:
    params = {"types": "im", "limit": 200}
    data = _call(hdrs, "conversations.list", params=params)
    return [ch["id"] for ch in (data.get("channels") or [])]


def _fetch_users(hdrs: dict) -> dict[str, str]:
    """Return {user_id: display_name_or_email}."""
    users: dict[str, str] = {}
    cursor: str | None = None
    while True:
        params: dict = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _call(hdrs, "users.list", params=params)
        for u in data.get("members") or []:
            profile = u.get("profile") or {}
            name = profile.get("display_name") or profile.get("real_name") or u.get("name") or u["id"]
            users[u["id"]] = name
        next_cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not next_cursor:
            break
        cursor = next_cursor
    return users


def _history(hdrs: dict, channel_id: str, oldest_ts: str | None):
    params: dict = {"channel": channel_id, "limit": PAGE_SIZE}
    if oldest_ts:
        params["oldest"] = oldest_ts
    while True:
        data = _call(hdrs, "conversations.history", params=params)
        if not data.get("ok"):
            err = data.get("error") or "unknown"
            if err == "channel_not_found":
                print(f"[slack] channel not accessible: {channel_id}")
                return
            raise RuntimeError(f"[slack] conversations.history error: {err}")
        yield from (data.get("messages") or [])
        if not data.get("has_more"):
            return
        params["cursor"] = data["response_metadata"]["next_cursor"]


def _replies(hdrs: dict, channel_id: str, thread_ts: str):
    params: dict = {"channel": channel_id, "ts": thread_ts, "limit": PAGE_SIZE}
    first = True
    while True:
        data = _call(hdrs, "conversations.replies", params=params)
        msgs = data.get("messages") or []
        # First message is the root — skip it (already have it)
        yield from (msgs[1:] if first else msgs)
        first = False
        if not data.get("has_more"):
            return
        params["cursor"] = data["response_metadata"]["next_cursor"]


def _call(hdrs: dict, method: str, params: dict | None = None) -> dict:
    _throttle()
    while True:
        r = requests.get(
            f"{SLACK_API}/{method}",
            headers=hdrs,
            params=params or {},
            timeout=30,
        )
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After") or 10)
            print(f"[slack] rate-limited on {method}, waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def _throttle() -> None:
    global _LAST_REQUEST_TS
    now = time.monotonic()
    gap = now - _LAST_REQUEST_TS
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    _LAST_REQUEST_TS = time.monotonic()


# ---------- Utilities ----------

def _iso_to_ts(iso: str) -> str:
    """Convert ISO-8601 to Slack ts (Unix seconds as string)."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return str(dt.timestamp())
    except ValueError:
        return iso


def _ts_to_iso(ts: str) -> str:
    """Convert Slack ts (Unix seconds.microseconds) to ISO-8601 UTC."""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError):
        return ts


def _plain(text: str) -> str:
    """Strip Slack mrkdwn user-mention syntax <@Uxxxx> → @Uxxxx."""
    import re
    return re.sub(r"<@(U[A-Z0-9]+)>", r"@\1", text or "").strip()
