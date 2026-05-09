"""ETL orchestrator.

Reads the active workspace's sources.yaml, opens the workspace graph
DB, applies schema, and runs each enabled source's `sync()` in turn.

By default each source pulls only items updated since its last
recorded sync (see library.sync_state). Pass --full to ignore that
state and re-fetch everything.

Source `sync()` calls run in parallel by default — they are I/O-bound
(API calls, filesystem walks) and independent. Pass --sequential to
fall back to the old in-order behavior (useful when debugging a
specific source or when the embedded DB is overwhelmed).

Usage:
    python -m library.sources.run                  # delta sync, all enabled sources, parallel
    python -m library.sources.run --source jira    # one source only
    python -m library.sources.run --full           # full re-sync (ignore sync_state)
    python -m library.sources.run --sequential     # one source at a time
    python -m library.sources.run --dry-run        # config check, no DB writes
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from graph import builder
from library.sources import config as source_config
from library.sources import github as github_source
from library.sources import github_issues as github_issues_source
from library.sources import jira as jira_source
from library.sources import confluence as confluence_source
from library.sources import gdrive_gemini as gdrive_gemini_source
from library.sources import markdown_dirs as markdown_dirs_source
from library.sources import notion as notion_source

DISPATCH = {
    "jira": jira_source.sync,
    "github": github_source.sync,
    "github_issues": github_issues_source.sync,
    "gdrive_gemini": gdrive_gemini_source.sync,
    "markdown_dirs": markdown_dirs_source.sync,
    "notion": notion_source.sync,
    "confluence": confluence_source.sync,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ETL for the active workspace.")
    parser.add_argument("--source", help="Run only this source (default: all enabled).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve config but do not open the DB or write anything.")
    parser.add_argument("--full", action="store_true",
                        help="Ignore sync_state and re-fetch everything.")
    parser.add_argument("--sequential", action="store_true",
                        help="Run sources one at a time instead of in parallel.")
    parser.add_argument("--max-workers", type=int, default=8,
                        help="Maximum parallel sources (default: 8).")
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

    # Apply schema once on the main thread; per-source workers each open
    # their own connection to the same SurrealKV directory.
    builder.apply_schema(builder.connect())

    runnable = []
    for source in enabled:
        fn = DISPATCH.get(source.name)
        if fn is None:
            print(f"[run] no ETL implemented for source '{source.name}', skipping")
            continue
        runnable.append((source, fn))

    if args.sequential or len(runnable) == 1:
        failures = _run_sequential(runnable, args.full)
    else:
        failures = _run_parallel(runnable, args.full, args.max_workers)

    if failures:
        sys.exit(1)


def _run_one(source, fn, full: bool):
    """Open a fresh DB connection in this thread and run the source's sync."""
    db = builder.connect()
    settings = {**source.settings, "full": full}
    return fn(db, settings, source.auth)


def _run_sequential(runnable, full: bool) -> int:
    failures = 0
    for source, fn in runnable:
        try:
            stats = _run_one(source, fn, full)
            print(f"[run] {source.name}: {stats}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[run] {source.name} FAILED: {exc}", file=sys.stderr)
    return failures


def _run_parallel(runnable, full: bool, max_workers: int) -> int:
    failures = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, len(runnable))) as pool:
        futures = {pool.submit(_run_one, source, fn, full): source.name
                   for source, fn in runnable}
        for future in as_completed(futures):
            name = futures[future]
            try:
                stats = future.result()
                print(f"[run] {name}: {stats}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"[run] {name} FAILED: {exc}", file=sys.stderr)
    return failures


if __name__ == "__main__":
    main()
