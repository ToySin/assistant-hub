"""Event timeline for since-last-session deltas.

Each ETL run compares the prior graph state of an item against the
incoming source data and emits typed events (issue.opened, .closed,
.status_changed, .title_changed) into a workspace-local SQLite store.

`/briefing` reads recent events to show "what changed while I was
gone". `/monitor mark-replayed` resets that cursor.

DB location: `<workspace>/db/events.db` (gitignored, regenerable).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from library.workspace import get_workspace_path

DB_FILENAME = "events.db"

CLOSED_STATUSES = {"closed", "done", "resolved", "complete", "completed"}


def _db_path(workspace: str | None = None) -> Path:
    return get_workspace_path(workspace) / "db" / DB_FILENAME


@contextmanager
def _conn(workspace: str | None = None):
    path = _db_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source      TEXT NOT NULL,
    scope       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'new',
    resolution  TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_subject ON events(source, subject_key);
CREATE INDEX IF NOT EXISTS idx_events_status  ON events(status);

CREATE TABLE IF NOT EXISTS markers (
    name TEXT PRIMARY KEY,
    ts   TEXT NOT NULL
);
"""

_MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'new'",
    "ALTER TABLE events ADD COLUMN resolution TEXT",
]


def init(workspace: str | None = None) -> None:
    with _conn(workspace) as conn:
        conn.executescript(_SCHEMA)
        # Idempotent column migrations for existing DBs created before
        # the status/resolution columns were added.
        for sql in _MIGRATIONS:
            try:
                conn.execute(sql)
            except Exception:  # noqa: BLE001
                pass  # column already exists


def emit(source: str, scope: str, kind: str, subject_key: str,
         payload: dict | None = None, workspace: str | None = None) -> None:
    init(workspace)
    with _conn(workspace) as conn:
        conn.execute(
            "INSERT INTO events (source, scope, kind, subject_key, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, scope, kind, subject_key,
             json.dumps(payload or {}, ensure_ascii=False)),
        )


def read_issue_state(db: Any, source: str, external_key: str) -> dict | None:
    """Return the current graph state of an Issue, or None if it has
    never been ingested. Used to diff against the next sync's payload."""
    res = db.query(
        "SELECT title, status FROM Issue "
        "WHERE source = $s AND external_key = $k LIMIT 1;",
        {"s": source, "k": external_key},
    )
    if isinstance(res, list) and res:
        first = res[0]
        if isinstance(first, list) and first:
            first = first[0]
        if isinstance(first, dict):
            return {"title": first.get("title"), "status": first.get("status")}
    return None


def emit_issue_diff(source_name: str, scope: str, external_key: str,
                    prior: dict | None, new: dict,
                    workspace: str | None = None) -> None:
    """Compare prior graph state with the new payload and emit events.

    `source_name` is the ETL source label (e.g. "github_issues",
    "jira") — distinct from the unified Issue.source field, which is
    "github" or "jira"."""
    if prior is None:
        emit(source_name, scope, "issue.opened", external_key, {
            "title": new.get("title", ""),
            "status": new.get("status", ""),
        }, workspace)
        return

    prior_status = (prior.get("status") or "")
    new_status = (new.get("status") or "")
    if prior_status != new_status:
        emit(source_name, scope, "issue.status_changed", external_key, {
            "from": prior_status, "to": new_status,
        }, workspace)
        if new_status.lower() in CLOSED_STATUSES and prior_status.lower() not in CLOSED_STATUSES:
            emit(source_name, scope, "issue.closed", external_key, {}, workspace)
        elif prior_status.lower() in CLOSED_STATUSES and new_status.lower() not in CLOSED_STATUSES:
            emit(source_name, scope, "issue.reopened", external_key, {}, workspace)

    if (prior.get("title") or "") != (new.get("title") or ""):
        emit(source_name, scope, "issue.title_changed", external_key, {
            "from": prior.get("title", ""), "to": new.get("title", ""),
        }, workspace)


def timeline(since: str | None = None, limit: int = 50,
             workspace: str | None = None) -> list[dict]:
    init(workspace)
    sql = "SELECT * FROM events"
    params: list = []
    if since:
        sql += " WHERE ts >= ?"
        params.append(since)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with _conn(workspace) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def since_last_replay(limit: int = 50,
                      workspace: str | None = None) -> list[dict]:
    """Events since the last replay cursor, excluding already-resolved ones."""
    init(workspace)
    with _conn(workspace) as conn:
        row = conn.execute(
            "SELECT ts FROM markers WHERE name = 'last_replay'"
        ).fetchone()
        marker = row["ts"] if row else None
    rows = timeline(since=marker, limit=limit, workspace=workspace)
    return [r for r in rows if r.get("status") != "resolved"]


def get_event(event_id: int, workspace: str | None = None) -> dict | None:
    init(workspace)
    with _conn(workspace) as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?",
                           (event_id,)).fetchone()
    return dict(row) if row else None


def mark_resolved(
    event_id: int,
    note: str = "",
    runbook_id: int | None = None,
    workspace: str | None = None,
) -> bool:
    """Mark a single event as resolved, recording an optional note and
    the runbook that handled it (if any). Returns True if the row was
    found and updated."""
    init(workspace)
    resolution = json.dumps(
        {"note": note, "runbook_id": runbook_id}, ensure_ascii=False
    )
    with _conn(workspace) as conn:
        cur = conn.execute(
            "UPDATE events SET status = 'resolved', resolution = ? WHERE id = ?",
            (resolution, event_id),
        )
    return cur.rowcount > 0


def mark_replayed(workspace: str | None = None) -> None:
    init(workspace)
    with _conn(workspace) as conn:
        conn.execute(
            "INSERT INTO markers (name, ts) VALUES ('last_replay', "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
            "ON CONFLICT(name) DO UPDATE SET "
            "ts = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        )


def suggest_runbooks(workspace: str | None = None) -> list[dict]:
    """List (kind, source) groups that have events but no covering
    runbook. The first time a pattern shows up there's nothing to
    automate; the second time you've already done it manually and a
    runbook is the obvious next step. This surfaces those gaps.

    Each suggestion has: kind, source, count (events), latest event
    id, sample subject_key.
    """
    from library import runbooks  # avoid circular import at module load

    init(workspace)
    with _conn(workspace) as conn:
        groups = conn.execute(
            """
            SELECT kind, source, COUNT(*) AS n,
                   MAX(id) AS latest_id,
                   MAX(subject_key) AS sample_subject
            FROM events
            GROUP BY kind, source
            ORDER BY n DESC
            """
        ).fetchall()

    suggestions: list[dict] = []
    for g in groups:
        sample_event = {
            "kind": g["kind"], "source": g["source"], "subject_key": "",
        }
        # Ask runbooks if any pattern covers this kind+source. Empty
        # subject_key means we ignore subject_pattern filters here —
        # any covering runbook with a generic pattern still counts.
        covered = bool(runbooks.match_event(sample_event, workspace=workspace))
        if covered:
            continue
        suggestions.append({
            "kind": g["kind"], "source": g["source"], "count": g["n"],
            "latest_event_id": g["latest_id"],
            "sample_subject": g["sample_subject"],
        })
    return suggestions


def stats(workspace: str | None = None) -> dict:
    init(workspace)
    with _conn(workspace) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        by_kind = [dict(r) for r in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM events GROUP BY kind ORDER BY n DESC"
        ).fetchall()]
    return {"total": total, "by_kind": by_kind}


def _format_event(row: dict) -> str:
    payload = json.loads(row.get("payload") or "{}")
    parts = [f"{row['ts']}  [{row['source']}] {row['kind']}  {row['subject_key']}"]
    summary = ""
    if row["kind"] == "issue.status_changed":
        summary = f"  {payload.get('from', '?')} -> {payload.get('to', '?')}"
    elif row["kind"] == "issue.title_changed":
        summary = f"  {payload.get('from', '')!r} -> {payload.get('to', '')!r}"
    elif row["kind"] == "issue.opened":
        summary = f"  {payload.get('title', '')}"
    return parts[0] + summary


def main() -> int:
    parser = argparse.ArgumentParser(prog="library.monitor",
                                     description="event timeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tl = sub.add_parser("timeline", help="list recent events")
    p_tl.add_argument("--since", help="ISO timestamp (default: all)")
    p_tl.add_argument("--limit", type=int, default=50)

    sub.add_parser("since-last-replay",
                   help="events since the last /briefing replay")
    sub.add_parser("mark-replayed",
                   help="advance the replay cursor to now")
    sub.add_parser("stats", help="event counts by kind")
    sub.add_parser("suggest",
                   help="list (kind, source) groups missing runbook coverage")

    args = parser.parse_args()

    if args.cmd == "timeline":
        rows = timeline(since=args.since, limit=args.limit)
    elif args.cmd == "since-last-replay":
        rows = since_last_replay()
    elif args.cmd == "mark-replayed":
        mark_replayed()
        print("replay cursor advanced.")
        return 0
    elif args.cmd == "stats":
        s = stats()
        print(f"total: {s['total']}")
        for row in s["by_kind"]:
            print(f"  {row['kind']:25} {row['n']}")
        return 0
    elif args.cmd == "suggest":
        sugs = suggest_runbooks()
        if not sugs:
            print("(every event kind already has a covering runbook)")
            return 0
        for s in sugs:
            print(f"  kind={s['kind']:22} source={s['source']:18} "
                  f"count={s['count']:>3}  latest_event=#{s['latest_event_id']}  "
                  f"sample={s['sample_subject']}")
        print()
        print("To capture one as a runbook:")
        print("  python -m library.runbooks create --name '<short>' "
              "--kind <kind> --source <source> --command '<cmd>' --from-event <id>")
        return 0
    else:
        parser.print_help()
        return 2

    if not rows:
        print("(no events)")
        return 0
    for row in rows:
        print(_format_event(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
