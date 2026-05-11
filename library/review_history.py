"""Review history store for /check-review and /apply-review.

Tracks which PR review comments have been replied to so re-runs of
/check-review pending don't re-show comments you already addressed.

Storage: `<workspace>/review-history.yaml` (gitignored — it contains
reviewer identities and comment excerpts that should stay local).

Entry shape:
  pr:          owner/repo#N
  comment_id:  <github comment id>
  action:      applied | reply-only | skipped
  replied_at:  ISO-8601 UTC
  note:        optional free-text (e.g. "linked PR #42")
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from library.workspace import get_workspace_path


def _path(workspace: str | None = None) -> Path:
    return get_workspace_path(workspace) / "review-history.yaml"


def _load(workspace: str | None = None) -> dict:
    p = _path(workspace)
    if not p.exists():
        return {"entries": []}
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            return {"entries": []}
        if "entries" not in data:
            data["entries"] = []
        return data
    except Exception:
        return {"entries": []}


def _save(data: dict, workspace: str | None = None) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))


def seen_comment_ids(workspace: str | None = None) -> set[int]:
    """Return the set of comment IDs already in the history file."""
    data = _load(workspace)
    return {int(e["comment_id"]) for e in data.get("entries", [])
            if e.get("comment_id")}


def append(
    pr: str,
    comment_id: int,
    action: str,
    note: str = "",
    workspace: str | None = None,
) -> None:
    """Append one entry. `action` should be 'applied', 'reply-only', or 'skipped'."""
    data = _load(workspace)
    data["entries"].append({
        "pr": pr,
        "comment_id": comment_id,
        "action": action,
        "replied_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": note or "",
    })
    _save(data, workspace)


def history(limit: int = 20, workspace: str | None = None) -> list[dict]:
    """Return the last `limit` entries, most recent first."""
    data = _load(workspace)
    return list(reversed(data.get("entries", [])))[:limit]


def clear(workspace: str | None = None) -> int:
    """Wipe all entries. Returns the count that was cleared."""
    data = _load(workspace)
    n = len(data.get("entries", []))
    _save({"entries": []}, workspace)
    return n


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="library.review_history",
                                     description="review comment history")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_app = sub.add_parser("append", help="record a processed comment")
    p_app.add_argument("--pr", required=True, help="owner/repo#N")
    p_app.add_argument("--comment-id", type=int, required=True)
    p_app.add_argument("--action", required=True,
                       choices=["applied", "reply-only", "skipped"])
    p_app.add_argument("--note", default="")

    p_hist = sub.add_parser("history", help="show recent entries")
    p_hist.add_argument("--limit", type=int, default=20)

    sub.add_parser("clear", help="wipe all entries (no undo)")

    args = parser.parse_args()

    if args.cmd == "append":
        append(args.pr, args.comment_id, args.action, args.note)
        print(f"recorded {args.action} on comment #{args.comment_id} in {args.pr}")

    elif args.cmd == "history":
        rows = history(args.limit)
        if not rows:
            print("(no entries)")
            return
        for e in rows:
            note = f"  — {e['note']}" if e.get("note") else ""
            print(f"{e.get('replied_at','')}  [{e.get('action','')}]  "
                  f"{e.get('pr','')} comment#{e.get('comment_id','')}{note}")

    elif args.cmd == "clear":
        n = clear()
        print(f"cleared {n} entries.")


if __name__ == "__main__":
    main()
