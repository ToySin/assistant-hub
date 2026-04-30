"""ETL orchestrator.

Reads the active workspace's sources.yaml, opens the workspace graph
DB, applies schema, and runs each enabled source's `sync()` in turn.

Usage:
    python -m library.sources.run                  # all enabled sources
    python -m library.sources.run --source jira    # one source only
    python -m library.sources.run --dry-run        # config check, no DB writes
"""

from __future__ import annotations

import argparse
import sys

from graph import builder
from library.sources import config as source_config
from library.sources import github as github_source
from library.sources import jira as jira_source

DISPATCH = {
    "jira": jira_source.sync,
    "github": github_source.sync,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ETL for the active workspace.")
    parser.add_argument("--source", help="Run only this source (default: all enabled).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve config but do not open the DB or write anything.")
    args = parser.parse_args()

    enabled = source_config.load()
    if args.source:
        enabled = [s for s in enabled if s.name == args.source]
    if not enabled:
        print("[run] no enabled sources matched. Edit sources.yaml or pass a different --source.")
        return

    print(f"[run] enabled sources: {', '.join(s.name for s in enabled)}")
    if args.dry_run:
        for s in enabled:
            print(f"  - {s.name}: settings={s.settings}, auth={'<set>' if s.auth else '<none>'}")
        return

    db = builder.connect()
    builder.apply_schema(db)

    failures = 0
    for source in enabled:
        fn = DISPATCH.get(source.name)
        if fn is None:
            print(f"[run] no ETL implemented for source '{source.name}', skipping")
            continue
        try:
            stats = fn(db, source.settings, source.auth)
            print(f"[run] {source.name}: {stats}")
        except Exception as exc:  # noqa: BLE001 — report and continue
            failures += 1
            print(f"[run] {source.name} FAILED: {exc}", file=sys.stderr)

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
