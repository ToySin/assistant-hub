"""Self-reinforcing runbook store.

A runbook is a (pattern, steps) recipe. Pattern decides which events the
runbook applies to; steps describe what to do. Each execution records
success or failure, and the automation level walks up
(manual → semi-auto → auto) as evidence accumulates and walks back down
on failure. Thresholds live in `promotion_policies` so different work
contexts can tune aggression independently.

Mirrors the hub `monitor_tool/db.py` runbook design — same column set,
same lifecycle semantics, smaller surface.

Lives next to monitor's events in `<workspace>/db/events.db`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

from library.workspace import get_workspace_path

DB_FILENAME = "events.db"

LEVELS = ("manual", "semi-auto", "auto")

# Default policy seeded on first init. Tweak via `runbooks policy` CLI
# (TODO: add) or directly in SQL — values are hot-read on every promote.
DEFAULT_POLICY = {
    "name": "default",
    "to_semi_min_success": 1,             # manual → semi-auto after N successes
    "to_auto_min_success": 2,             # semi-auto → auto cumulative successes
    "to_auto_max_fail": 0,                # blocks promotion if any failures
    "demote_auto_min_fail": 1,            # auto → semi-auto after N failures
    "demote_semi_fail_gte_success": 1,    # 1 = demote semi-auto when fail ≥ success
}


@dataclass
class Runbook:
    id: int
    name: str
    pattern: dict
    steps: list[dict]
    automation_level: str
    applied: int
    succeeded: int
    failed: int
    created_from_event_id: int | None
    policy_id: int
    pattern_hash: str
    created_at: str
    updated_at: str


@dataclass
class PromotionPolicy:
    id: int
    name: str
    to_semi_min_success: int
    to_auto_min_success: int
    to_auto_max_fail: int
    demote_auto_min_fail: int
    demote_semi_fail_gte_success: int


def _db_path(workspace: str | None = None) -> Path:
    return get_workspace_path(workspace) / "db" / DB_FILENAME


@contextmanager
def _conn(workspace: str | None = None):
    path = _db_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS promotion_policies (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    name                          TEXT NOT NULL UNIQUE,
    to_semi_min_success           INTEGER NOT NULL DEFAULT 1,
    to_auto_min_success           INTEGER NOT NULL DEFAULT 2,
    to_auto_max_fail              INTEGER NOT NULL DEFAULT 0,
    demote_auto_min_fail          INTEGER NOT NULL DEFAULT 1,
    demote_semi_fail_gte_success  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS runbooks (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_hash          TEXT NOT NULL UNIQUE,
    name                  TEXT NOT NULL,
    pattern               TEXT NOT NULL,
    steps                 TEXT NOT NULL,
    automation_level      TEXT NOT NULL DEFAULT 'manual',
    applied               INTEGER NOT NULL DEFAULT 0,
    succeeded             INTEGER NOT NULL DEFAULT 0,
    failed                INTEGER NOT NULL DEFAULT 0,
    created_from_event_id INTEGER,
    policy_id             INTEGER NOT NULL DEFAULT 1
                          REFERENCES promotion_policies(id),
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_runbooks_level ON runbooks(automation_level);
"""


def init(workspace: str | None = None) -> None:
    with _conn(workspace) as conn:
        conn.executescript(_SCHEMA)
        # Seed the default policy at id=1 if absent.
        existing = conn.execute(
            "SELECT id FROM promotion_policies WHERE name = ?",
            (DEFAULT_POLICY["name"],),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO promotion_policies
                    (name, to_semi_min_success, to_auto_min_success,
                     to_auto_max_fail, demote_auto_min_fail,
                     demote_semi_fail_gte_success)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (DEFAULT_POLICY["name"],
                 DEFAULT_POLICY["to_semi_min_success"],
                 DEFAULT_POLICY["to_auto_min_success"],
                 DEFAULT_POLICY["to_auto_max_fail"],
                 DEFAULT_POLICY["demote_auto_min_fail"],
                 DEFAULT_POLICY["demote_semi_fail_gte_success"]),
            )


def _row_to_runbook(row: sqlite3.Row) -> Runbook:
    return Runbook(
        id=row["id"],
        name=row["name"],
        pattern=json.loads(row["pattern"]),
        steps=json.loads(row["steps"]),
        automation_level=row["automation_level"],
        applied=row["applied"],
        succeeded=row["succeeded"],
        failed=row["failed"],
        created_from_event_id=row["created_from_event_id"],
        policy_id=row["policy_id"],
        pattern_hash=row["pattern_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_policy(row: sqlite3.Row) -> PromotionPolicy:
    return PromotionPolicy(
        id=row["id"], name=row["name"],
        to_semi_min_success=row["to_semi_min_success"],
        to_auto_min_success=row["to_auto_min_success"],
        to_auto_max_fail=row["to_auto_max_fail"],
        demote_auto_min_fail=row["demote_auto_min_fail"],
        demote_semi_fail_gte_success=row["demote_semi_fail_gte_success"],
    )


def _hash_pattern(pattern: dict) -> str:
    return hashlib.sha1(
        json.dumps(pattern, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


class DuplicatePatternError(RuntimeError):
    """Raised when create() collides with an existing pattern_hash."""

    def __init__(self, existing: Runbook):
        self.existing = existing
        super().__init__(
            f"runbook #{existing.id} ({existing.name}) already covers this pattern"
        )


def create(name: str, pattern: dict, steps: list[dict],
           created_from_event_id: int | None = None,
           automation_level: str = "manual",
           policy_id: int = 1,
           workspace: str | None = None) -> Runbook:
    """Insert a runbook. Raises DuplicatePatternError when a runbook
    with the same `pattern_hash` already exists — that's the dedup
    guarantee hub uses to keep the table tidy."""
    if automation_level not in LEVELS:
        raise ValueError(f"automation_level must be one of {LEVELS}")
    init(workspace)
    hashed = _hash_pattern(pattern)
    with _conn(workspace) as conn:
        existing = conn.execute(
            "SELECT * FROM runbooks WHERE pattern_hash = ?", (hashed,),
        ).fetchone()
        if existing is not None:
            raise DuplicatePatternError(_row_to_runbook(existing))
        cur = conn.execute(
            """
            INSERT INTO runbooks (pattern_hash, name, pattern, steps,
                                  automation_level, created_from_event_id,
                                  policy_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (hashed, name, json.dumps(pattern, sort_keys=True),
             json.dumps(steps), automation_level, created_from_event_id,
             policy_id),
        )
        rb_id = cur.lastrowid
        row = conn.execute("SELECT * FROM runbooks WHERE id = ?",
                           (rb_id,)).fetchone()
    return _row_to_runbook(row)


def list_(level: str | None = None,
          workspace: str | None = None) -> list[Runbook]:
    init(workspace)
    sql = "SELECT * FROM runbooks"
    params: list = []
    if level:
        sql += " WHERE automation_level = ?"
        params.append(level)
    sql += " ORDER BY succeeded DESC, id"
    with _conn(workspace) as conn:
        return [_row_to_runbook(r) for r in conn.execute(sql, params).fetchall()]


def get(runbook_id: int, workspace: str | None = None) -> Runbook | None:
    init(workspace)
    with _conn(workspace) as conn:
        row = conn.execute("SELECT * FROM runbooks WHERE id = ?",
                           (runbook_id,)).fetchone()
    return _row_to_runbook(row) if row else None


def get_policy(policy_id: int = 1,
               workspace: str | None = None) -> PromotionPolicy | None:
    init(workspace)
    with _conn(workspace) as conn:
        row = conn.execute("SELECT * FROM promotion_policies WHERE id = ?",
                           (policy_id,)).fetchone()
    return _row_to_policy(row) if row else None


def list_policies(workspace: str | None = None) -> list[PromotionPolicy]:
    init(workspace)
    with _conn(workspace) as conn:
        return [_row_to_policy(r) for r in conn.execute(
            "SELECT * FROM promotion_policies ORDER BY id"
        ).fetchall()]


def delete(runbook_id: int, workspace: str | None = None) -> bool:
    init(workspace)
    with _conn(workspace) as conn:
        cur = conn.execute("DELETE FROM runbooks WHERE id = ?", (runbook_id,))
    return cur.rowcount > 0


def match_event(event: dict, workspace: str | None = None) -> list[Runbook]:
    """Return all runbooks whose pattern matches the given event row.
    Pattern keys (all optional except `kind`):
      kind             — exact match against event.kind
      source           — exact match against event.source
      subject_pattern  — Python regex against event.subject_key
    Auto-level matches first, then semi-auto, then manual."""
    matches: list[Runbook] = []
    for rb in list_(workspace=workspace):
        p = rb.pattern
        if p.get("kind") and p["kind"] != event.get("kind"):
            continue
        if p.get("source") and p["source"] != event.get("source"):
            continue
        sp = p.get("subject_pattern")
        if sp and not re.search(sp, event.get("subject_key") or ""):
            continue
        matches.append(rb)
    matches.sort(key=lambda r: (LEVELS.index(r.automation_level)
                                if r.automation_level in LEVELS else 99,
                                -r.succeeded))
    return matches


def render_step(step: dict, event: dict) -> str:
    """Substitute $subject_key / $source / $kind / $payload_<key> into
    the step's command. Missing keys substitute as empty string. Steps
    of type='skill' return a "/<skill-name>" marker — execution layer
    decides how to invoke."""
    if step.get("type") == "skill":
        return f"/{step.get('name', '').lstrip('/')}"
    if step.get("type") not in (None, "command"):
        raise ValueError(f"unsupported step type: {step.get('type')}")
    cmd = step.get("cmd") or ""
    payload = event.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    mapping = {
        "subject_key": event.get("subject_key", ""),
        "source": event.get("source", ""),
        "scope": event.get("scope", ""),
        "kind": event.get("kind", ""),
    }
    for k, v in (payload or {}).items():
        mapping[f"payload_{k}"] = "" if v is None else str(v)
    return Template(cmd).safe_substitute(mapping)


def record_outcome(runbook_id: int, outcome: str,
                   workspace: str | None = None) -> Runbook | None:
    """Increment counters and apply the runbook's promotion_policy.

    Successes only promote (manual → semi-auto → auto). Failures only
    demote (auto → semi-auto, semi-auto → manual when fail ≥ success).
    The policy decides exact thresholds — read fresh from the DB on
    every call so policy edits take effect without restart."""
    if outcome not in ("success", "fail"):
        raise ValueError("outcome must be 'success' or 'fail'")
    init(workspace)
    with _conn(workspace) as conn:
        row = conn.execute("SELECT * FROM runbooks WHERE id = ?",
                           (runbook_id,)).fetchone()
        if row is None:
            return None
        policy_row = conn.execute(
            "SELECT * FROM promotion_policies WHERE id = ?",
            (row["policy_id"],),
        ).fetchone()
        policy = _row_to_policy(policy_row) if policy_row else None
        applied = row["applied"] + 1
        succeeded = row["succeeded"] + (1 if outcome == "success" else 0)
        failed = row["failed"] + (1 if outcome == "fail" else 0)
        level = _next_level(row["automation_level"], outcome,
                            succeeded, failed, policy)
        conn.execute(
            """
            UPDATE runbooks
            SET applied = ?, succeeded = ?, failed = ?,
                automation_level = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (applied, succeeded, failed, level, runbook_id),
        )
        row = conn.execute("SELECT * FROM runbooks WHERE id = ?",
                           (runbook_id,)).fetchone()
    return _row_to_runbook(row)


def _next_level(current: str, outcome: str, succeeded: int, failed: int,
                policy: PromotionPolicy | None) -> str:
    """Apply the lifecycle rules.

    Falls back to a sensible default policy when the row is gone,
    so a missing/corrupt policy never freezes the system."""
    if policy is None:
        policy = PromotionPolicy(
            id=1, name="fallback",
            to_semi_min_success=1, to_auto_min_success=2,
            to_auto_max_fail=0, demote_auto_min_fail=1,
            demote_semi_fail_gte_success=1,
        )
    if outcome == "success":
        if current == "manual" and succeeded >= policy.to_semi_min_success:
            return "semi-auto"
        if (current == "semi-auto"
                and succeeded >= policy.to_auto_min_success
                and failed <= policy.to_auto_max_fail):
            return "auto"
        return current
    # outcome == "fail"
    if current == "auto" and failed >= policy.demote_auto_min_fail:
        return "semi-auto"
    if (current == "semi-auto"
            and policy.demote_semi_fail_gte_success
            and failed >= succeeded):
        return "manual"
    return current


# --- CLI ------------------------------------------------------------

def _format_short(rb: Runbook) -> str:
    return (f"#{rb.id} [{rb.automation_level}] {rb.name}  "
            f"({rb.succeeded}✓ / {rb.failed}✗ / {rb.applied} total)")


def _print_full(rb: Runbook) -> None:
    print(_format_short(rb))
    print(f"  pattern: {json.dumps(rb.pattern)}  hash={rb.pattern_hash}")
    for i, step in enumerate(rb.steps, 1):
        print(f"  step {i}: {step}")
    if rb.created_from_event_id:
        print(f"  created from event #{rb.created_from_event_id}")
    print(f"  policy #{rb.policy_id}, "
          f"created {rb.created_at}, updated {rb.updated_at}")


def _load_event(event_id: int, workspace: str | None = None) -> dict | None:
    db_path = _db_path(workspace)
    if not db_path.is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM events WHERE id = ?",
                           (event_id,)).fetchone()
    return dict(row) if row else None


def main() -> int:
    parser = argparse.ArgumentParser(prog="library.runbooks",
                                     description="runbook store + lifecycle")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list runbooks")
    p_list.add_argument("--level", choices=LEVELS)

    p_view = sub.add_parser("view", help="show one runbook in detail")
    p_view.add_argument("id", type=int)

    p_create = sub.add_parser("create", help="create a runbook")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--kind", required=True,
                          help="event kind to match (e.g. issue.closed)")
    p_create.add_argument("--source", help="optional source filter")
    p_create.add_argument("--subject-pattern",
                          help="optional regex against event.subject_key")
    p_create.add_argument("--command", action="append", default=[], required=True,
                          help="shell command (repeat for multi-step)")
    p_create.add_argument("--from-event", type=int)
    p_create.add_argument("--level", choices=LEVELS, default="manual")
    p_create.add_argument("--policy-id", type=int, default=1)

    p_delete = sub.add_parser("delete", help="delete a runbook")
    p_delete.add_argument("id", type=int)

    p_match = sub.add_parser("match", help="show runbooks matching an event")
    p_match.add_argument("event_id", type=int)

    p_render = sub.add_parser("render",
                              help="render runbook commands against an event")
    p_render.add_argument("runbook_id", type=int)
    p_render.add_argument("event_id", type=int)

    p_record = sub.add_parser("record", help="record an outcome")
    p_record.add_argument("id", type=int)
    p_record.add_argument("outcome", choices=["success", "fail"])

    sub.add_parser("policies", help="list promotion policies")

    args = parser.parse_args()

    if args.cmd == "list":
        rbs = list_(level=args.level)
        if not rbs:
            print("(no runbooks)")
            return 0
        for rb in rbs:
            print(_format_short(rb))
        return 0

    if args.cmd == "view":
        rb = get(args.id)
        if rb is None:
            print(f"runbook #{args.id} not found", file=sys.stderr)
            return 1
        _print_full(rb)
        return 0

    if args.cmd == "create":
        pattern: dict[str, Any] = {"kind": args.kind}
        if args.source:
            pattern["source"] = args.source
        if args.subject_pattern:
            pattern["subject_pattern"] = args.subject_pattern
        steps = [{"type": "command", "cmd": c} for c in args.command]
        try:
            rb = create(args.name, pattern, steps,
                        created_from_event_id=args.from_event,
                        automation_level=args.level,
                        policy_id=args.policy_id)
        except DuplicatePatternError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        _print_full(rb)
        return 0

    if args.cmd == "delete":
        if delete(args.id):
            print(f"deleted runbook #{args.id}")
            return 0
        print(f"runbook #{args.id} not found", file=sys.stderr)
        return 1

    if args.cmd == "match":
        event = _load_event(args.event_id)
        if event is None:
            print(f"event #{args.event_id} not found", file=sys.stderr)
            return 1
        matches = match_event(event)
        if not matches:
            print("(no runbooks match)")
            return 0
        for rb in matches:
            print(_format_short(rb))
        return 0

    if args.cmd == "render":
        rb = get(args.runbook_id)
        if rb is None:
            print(f"runbook #{args.runbook_id} not found", file=sys.stderr)
            return 1
        event = _load_event(args.event_id)
        if event is None:
            print(f"event #{args.event_id} not found", file=sys.stderr)
            return 1
        for i, step in enumerate(rb.steps, 1):
            print(f"# step {i}")
            print(render_step(step, event))
        return 0

    if args.cmd == "record":
        rb = record_outcome(args.id, args.outcome)
        if rb is None:
            print(f"runbook #{args.id} not found", file=sys.stderr)
            return 1
        _print_full(rb)
        return 0

    if args.cmd == "policies":
        for p in list_policies():
            print(f"#{p.id} {p.name}  "
                  f"manual->semi:{p.to_semi_min_success}succ  "
                  f"semi->auto:{p.to_auto_min_success}succ/{p.to_auto_max_fail}fail  "
                  f"demote auto:{p.demote_auto_min_fail}fail  "
                  f"demote semi: {'fail≥succ' if p.demote_semi_fail_gte_success else 'never'}")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
