"""Gmail ETL.

Fetches Gmail threads via the Gmail REST API and stores each thread as
a Note in the workspace graph. Threads are the natural unit — individual
messages within a thread are concatenated into the Note body with
From/Date headers for context.

Each thread Note:
  source      = "gmail"
  path        = "gmail:<thread_id>"
  title       = thread subject
  body        = concatenated messages with "From: ... Date: ...\n<text>" blocks
  modified_at = latest message internalDate (converted to ISO)
  labels      = list of Gmail label names (INBOX, SENT, etc.)

Participants (From / To / Cc) become Person nodes linked via
`participated_in` edges (role="sender" for From, "recipient" for others).
Jira keys + PR refs in body produce `references_issue` / `references_pr` edges.

Auth: ADC via gcloud, same as gcal/gdrive_gemini. `auth_env: GOOGLE_OAUTH_TOKEN`
overrides. ADC must include the `gmail.readonly` scope:
  gcloud auth application-default login \
    --scopes=...,https://www.googleapis.com/auth/gmail.readonly

Delta: `historyId`-based incremental sync (stored as 'hist:<id>' in
sync_state). Falls back to query-bounded re-seed when history expires
(typically after ~7–14 days of inactivity) or on `full: true`.

Settings (sources.yaml):
  query:       ""            Gmail search syntax, applied to initial seed.
                             Example: "newer_than:30d -from:notifications@github.com"
  max_threads: 200           cap for initial / full seed
  full:        false         ignore history cursor, re-seed from query
"""

from __future__ import annotations

import base64
import email as email_lib
import email.policy
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from surrealdb import Surreal

from graph import builder
from library import _gauth, sync_state

SOURCE_NAME = "gmail"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
PAGE_SIZE = 100


@dataclass
class SyncStats:
    threads: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str | None = None) -> SyncStats:
    query = settings.get("query") or ""
    max_threads = int(settings.get("max_threads") or 200)
    full = bool(settings.get("full"))

    hdrs = _gauth.headers(auth)
    scope = query or "_all"
    raw_cursor = None if full else sync_state.get(SOURCE_NAME, scope=scope)

    hist_id: str | None = None
    if raw_cursor and raw_cursor.startswith("hist:"):
        hist_id = raw_cursor[5:]
    started = sync_state.now_iso()

    stats = SyncStats()
    if hist_id and not full:
        try:
            _sync_incremental(db, hdrs, hist_id, stats)
        except _HistoryGoneError:
            hist_id = None
            _sync_full(db, hdrs, query, max_threads, stats)
    else:
        _sync_full(db, hdrs, query, max_threads, stats)

    # Fetch current historyId to use next time
    new_hist = _current_history_id(hdrs)
    if new_hist:
        sync_state.set_(SOURCE_NAME, scope=scope, ts=f"hist:{new_hist}")
    else:
        sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


class _HistoryGoneError(Exception):
    pass


# ---------- Full seed ----------

def _sync_full(
    db: Surreal, hdrs: dict, query: str, max_threads: int, stats: SyncStats,
) -> None:
    fetched = 0
    page_token: str | None = None
    while fetched < max_threads:
        params: dict = {"maxResults": min(PAGE_SIZE, max_threads - fetched)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{GMAIL_BASE}/threads", headers=hdrs, params=params, timeout=30)
        _check_google_error(r, "gmail threads.list")
        data = r.json()
        for stub in data.get("threads") or []:
            _ingest_thread(db, hdrs, stub["id"], stats)
            fetched += 1
            if fetched >= max_threads:
                break
        page_token = data.get("nextPageToken")
        if not page_token:
            break


# ---------- Incremental via historyId ----------

def _sync_incremental(
    db: Surreal, hdrs: dict, start_history_id: str, stats: SyncStats,
) -> None:
    params = {
        "startHistoryId": start_history_id,
        "historyTypes": "messageAdded",
    }
    page_token: str | None = None
    thread_ids: set[str] = set()
    while True:
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{GMAIL_BASE}/history", headers=hdrs, params=params, timeout=30)
        if r.status_code == 404:
            raise _HistoryGoneError()
        _check_google_error(r, "gmail history.list")
        data = r.json()
        for rec in data.get("history") or []:
            for added in rec.get("messagesAdded") or []:
                tid = (added.get("message") or {}).get("threadId")
                if tid:
                    thread_ids.add(tid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    for tid in thread_ids:
        _ingest_thread(db, hdrs, tid, stats)


def _current_history_id(hdrs: dict) -> str | None:
    r = requests.get(f"{GMAIL_BASE}/profile", headers=hdrs, timeout=15)
    if r.status_code != 200:
        return None
    return str(r.json().get("historyId") or "")


# ---------- Thread → Note ----------

def _ingest_thread(db: Surreal, hdrs: dict, thread_id: str, stats: SyncStats) -> None:
    r = requests.get(
        f"{GMAIL_BASE}/threads/{thread_id}",
        headers=hdrs,
        params={"format": "full"},
        timeout=30,
    )
    if r.status_code == 404:
        stats.skipped += 1
        return
    _check_google_error(r, f"gmail thread {thread_id}")
    thread = r.json()

    messages = thread.get("messages") or []
    if not messages:
        stats.skipped += 1
        return

    subject = _header(messages[0], "Subject") or "(no subject)"
    label_ids = set()
    for m in messages:
        label_ids.update(m.get("labelIds") or [])

    body_parts: list[str] = []
    participants: dict[str, str] = {}  # email → role
    latest_ts: int = 0

    for msg in messages:
        from_addr = _header(msg, "From") or ""
        to_addr = _header(msg, "To") or ""
        cc_addr = _header(msg, "Cc") or ""
        date_str = _header(msg, "Date") or ""
        text = _extract_text(msg)
        internal_date = int(msg.get("internalDate") or 0)
        if internal_date > latest_ts:
            latest_ts = internal_date

        block = f"From: {from_addr}  Date: {date_str}\n{text}"
        body_parts.append(block)

        for addr in _parse_addresses(from_addr):
            participants.setdefault(addr, "sender")
        for addr in _parse_addresses(to_addr) + _parse_addresses(cc_addr):
            participants.setdefault(addr, "recipient")

    body = "\n\n---\n\n".join(body_parts)
    modified_at = _ms_to_iso(latest_ts) if latest_ts else ""

    note_id = builder.upsert_note(
        db,
        source=SOURCE_NAME,
        path=f"gmail:{thread_id}",
        title=subject,
        body=body,
        modified_at=modified_at,
    )

    builder.link_note_references(db, note_id, body)

    for addr, role in participants.items():
        person_id = builder.upsert_person(db, addr)
        builder.relate_participation(db, person_id, note_id, role=role)

    stats.threads += 1


# ---------- Parsing helpers ----------

def _header(msg: dict, name: str) -> str:
    for h in (msg.get("payload") or {}).get("headers") or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value") or ""
    return ""


def _extract_text(msg: dict) -> str:
    """Recursively extract text/plain from a message payload."""
    payload = msg.get("payload") or {}
    return _extract_text_from_part(payload)


def _extract_text_from_part(part: dict) -> str:
    mime = part.get("mimeType") or ""
    if mime == "text/plain":
        data = (part.get("body") or {}).get("data") or ""
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    if mime == "text/html" and not part.get("parts"):
        data = (part.get("body") or {}).get("data") or ""
        if data:
            raw = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return _strip_html(raw)
    # Recurse into multipart
    parts = part.get("parts") or []
    # Prefer text/plain parts
    for p in parts:
        if (p.get("mimeType") or "").startswith("text/plain"):
            text = _extract_text_from_part(p)
            if text:
                return text
    for p in parts:
        text = _extract_text_from_part(p)
        if text:
            return text
    return ""


def _strip_html(html: str) -> str:
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self._parts.append(data)

        def get_text(self) -> str:
            return "".join(self._parts)

    s = _Stripper()
    s.feed(html)
    return s.get_text()


def _parse_addresses(field: str) -> list[str]:
    """Extract email addresses from a From/To/Cc header value."""
    if not field:
        return []
    result: list[str] = []
    for part in field.split(","):
        part = part.strip()
        # "Name <addr>" or just "addr"
        if "<" in part and ">" in part:
            addr = part[part.index("<") + 1:part.index(">")].strip()
        else:
            addr = part
        if "@" in addr:
            result.append(addr.lower())
    return result


def _ms_to_iso(ms: int) -> str:
    """Convert Gmail internalDate (milliseconds since epoch) to ISO-8601."""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_google_error(r: requests.Response, context: str) -> None:
    if r.status_code == 401:
        raise RuntimeError(
            f"{context}: 401 Unauthorized. ADC token may have expired or "
            "lack gmail.readonly scope. Re-run: "
            "gcloud auth application-default login --scopes=..."
        )
    if r.status_code == 403:
        msg = (r.json().get("error") or {}).get("message") or ""
        raise RuntimeError(f"{context}: 403 Forbidden — {msg}")
    r.raise_for_status()
