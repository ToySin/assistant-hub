"""GitHub Notifications ETL.

Pulls participating GitHub notifications via the `gh` CLI and stores
each as a Note in the workspace graph. Unlike the live-fetch in
library/briefing._fetch_gh_notifications(), this adapter keeps
notifications across sessions so they can be searched and cross-linked.

Each notification becomes a Note:
  source = "gh_notification"
  path   = <notification_id>
  title  = "[reason] repo: subject_title"
  body   = reason, repo, subject_url, updated_at, unread flag
  modified_at = notification.updated_at

If the subject URL is a pull request or issue that's already in the
graph (or becomes a stub via ensure_github_pr / ensure_issue), a
references_pr / references_issue edge is created. This connects the
"I was mentioned here" signal to the actual work item.

Auth: gh CLI handles GitHub auth — no auth_env needed.

Delta: uses `?since=<ISO>` on the GitHub Notifications API. Stores
cursor in sync_state. `full: true` fetches the last `since_days` days.

Settings (sources.yaml):
  participating_only: true    only notifications the user participated in
  all:               true     include read notifications (not just unread)
  since_days:        7        lookback window for initial / full sync
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from surrealdb import Surreal

from graph import builder, link_extractor
from library import sync_state

SOURCE_NAME = "gh_notification"


@dataclass
class SyncStats:
    notes: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str | None = None) -> SyncStats:
    participating_only = bool(settings.get("participating_only", True))
    include_all = bool(settings.get("all", True))
    since_days = int(settings.get("since_days") or 7)
    full = bool(settings.get("full"))

    scope = f"participating:{participating_only}|all:{include_all}"
    since = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    if full or not since:
        from datetime import datetime, timedelta, timezone
        since = (
            datetime.now(tz=timezone.utc) - timedelta(days=since_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    started = sync_state.now_iso()

    notifs = _fetch_notifications(since, participating_only, include_all)
    stats = SyncStats()
    for n in notifs:
        _ingest(db, n, stats)

    sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


# ---------- gh CLI ----------

def _fetch_notifications(
    since: str, participating_only: bool, include_all: bool,
) -> list[dict]:
    query = f"notifications?since={since}"
    if include_all:
        query += "&all=true"
    if participating_only:
        query += "&participating=true"

    try:
        r = subprocess.run(
            ["gh", "api", query],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            print(f"[gh_notification] gh api failed: {r.stderr.strip()}")
            return []
        return json.loads(r.stdout) or []
    except Exception as exc:
        print(f"[gh_notification] error: {exc}")
        return []


# ---------- Notification → Note ----------

def _ingest(db: Surreal, notif: dict, stats: SyncStats) -> None:
    notif_id = str(notif.get("id") or "")
    if not notif_id:
        stats.skipped += 1
        return

    reason = notif.get("reason") or ""
    repo = (notif.get("repository") or {}).get("full_name") or ""
    subject = notif.get("subject") or {}
    subject_title = subject.get("title") or ""
    subject_url = subject.get("url") or ""
    subject_type = subject.get("type") or ""
    updated_at = notif.get("updated_at") or ""
    unread = notif.get("unread", True)

    title = f"[{reason}] {repo}: {subject_title}"
    body = (
        f"reason: {reason}\n"
        f"repo: {repo}\n"
        f"type: {subject_type}\n"
        f"url: {subject_url}\n"
        f"updated: {updated_at}\n"
        f"unread: {unread}"
    )

    note_id = builder.upsert_note(
        db,
        source=SOURCE_NAME,
        path=notif_id,
        title=title,
        body=body,
        modified_at=updated_at,
    )

    # Wire to the underlying PR or Issue if we can resolve the API URL
    _link_subject(db, note_id, subject_url, subject_type)
    stats.notes += 1


def _link_subject(
    db: Surreal, note_id, subject_url: str, subject_type: str,
) -> None:
    if not subject_url:
        return

    if subject_type == "PullRequest":
        ref = link_extractor.extract_github_api_pr_ref(subject_url)
        if ref:
            pr_id = builder.ensure_github_pr(db, uid=ref)
            builder.relate(db, note_id, "references_pr", pr_id)

    elif subject_type == "Issue":
        result = link_extractor.extract_github_api_issue_ref(subject_url)
        if result:
            repo, num = result
            issue_id = builder.ensure_issue(db, source="github", external_key=f"{repo}#{num}")
            builder.relate(db, note_id, "references_issue", issue_id)
