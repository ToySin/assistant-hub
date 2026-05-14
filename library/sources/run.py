"""ETL orchestrator.

Reads the active workspace's sources.yaml, opens the workspace graph
DB, applies schema, and runs each enabled source's `sync()` in turn.

By default each source pulls only items updated since its last
recorded sync (see library.sync_state). Pass --full to ignore that
state and re-fetch everything.

Source `sync()` calls run sequentially by default. Embedded SurrealKV
treats concurrent writers from the same process as separate revisions
of the same store, so heavy parallel writes (e.g. Jira ingestion of
hundreds of issues during the same run as Confluence pages) hit
"Invalid revision" errors. Pass `--parallel` for I/O-bound runs that
won't write much, or wait for the per-source fetch/load split that
will let us parallelize fetches while serializing loads through one
shared connection.

Usage:
    python -m library.sources.run                  # delta sync, all enabled sources, sequential
    python -m library.sources.run --source jira    # one source only
    python -m library.sources.run --full           # full re-sync (ignore sync_state)
    python -m library.sources.run --parallel       # opt in (writes-light runs only)
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
from library.sources import gdrive_docs as gdrive_docs_source
from library.sources import gdrive_gemini as gdrive_gemini_source
from library.sources import markdown_dirs as markdown_dirs_source
from library.sources import gcal as gcal_source
from library.sources import github_notifications as gh_notifs_source
from library.sources import linear as linear_source
from library.sources import notion as notion_source
from library.sources import gmail as gmail_source
from library.sources import slack as slack_source

SOURCES = {
    "jira": jira_source,
    "github": github_source,
    "github_issues": github_issues_source,
    "gdrive_docs": gdrive_docs_source,
    "gdrive_gemini": gdrive_gemini_source,
    "markdown_dirs": markdown_dirs_source,
    "notion": notion_source,
    "confluence": confluence_source,
    "gcal": gcal_source,
    "github_notifications": gh_notifs_source,
    "linear": linear_source,
    "slack": slack_source,
    "gmail": gmail_source,
}


def _has_split(mod) -> bool:
    """A source supports parallel-fetch / serial-load if it exposes both
    `fetch(settings, auth)` and `load(db, fetch_result)`."""
    return hasattr(mod, "fetch") and hasattr(mod, "load")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ETL for the active workspace.")
    parser.add_argument("--source", help="Run only this source (default: all enabled).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve config but do not open the DB or write anything.")
    parser.add_argument("--full", action="store_true",
                        help="Ignore sync_state and re-fetch everything.")
    parser.add_argument("--parallel", action="store_true",
                        help="Run sources concurrently. Off by default — embedded "
                             "SurrealKV serializes writes per-process and concurrent "
                             "ETLs trip 'Invalid revision' errors. Safe for "
                             "writes-light runs (e.g. single-source debug).")
    parser.add_argument("--max-workers", type=int, default=8,
                        help="Maximum parallel sources when --parallel is on (default: 8).")
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
        mod = SOURCES.get(source.name)
        if mod is None:
            print(f"[run] no ETL implemented for source '{source.name}', skipping")
            continue
        runnable.append((source, mod))

    if args.parallel and len(runnable) > 1:
        failures = _run_parallel(runnable, args.full, args.max_workers)
    else:
        failures = _run_sequential(runnable, args.full)

    if failures:
        sys.exit(1)


def _run_sequential(runnable, full: bool) -> int:
    db = builder.connect()
    failures = 0
    for source, mod in runnable:
        settings = {**source.settings, "full": full}
        try:
            stats = mod.sync(db, settings, source.auth)
            print(f"[run] {source.name}: {stats}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[run] {source.name} FAILED: {exc}", file=sys.stderr)
    return failures


def _run_parallel(runnable, full: bool, max_workers: int) -> int:
    """Parallel-fetch / serial-load for sources that expose fetch+load.

    Embedded SurrealKV serializes writes per-process, so we keep loads
    single-threaded against one shared connection. I/O — REST/CLI/Drive
    calls — runs concurrently in a thread pool. Sources without split
    fall back to sync() in the same serial phase.
    """
    split: list[tuple] = []
    sync_only: list[tuple] = []
    for source, mod in runnable:
        (split if _has_split(mod) else sync_only).append((source, mod))

    failures = 0
    fetched: list[tuple] = []  # (source, mod, fetch_result)

    # Phase 1 — concurrent fetch for split-capable sources.
    if split:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(split))) as pool:
            futures = {}
            for source, mod in split:
                settings = {**source.settings, "full": full}
                futures[pool.submit(mod.fetch, settings, source.auth)] = (source, mod)
            for future in as_completed(futures):
                source, mod = futures[future]
                try:
                    fetched.append((source, mod, future.result()))
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    print(f"[run] {source.name} fetch FAILED: {exc}", file=sys.stderr)

    # Phase 2 — serial load through one shared connection.
    db = builder.connect()
    for source, mod, result in fetched:
        try:
            stats = mod.load(db, result)
            print(f"[run] {source.name}: {stats}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[run] {source.name} load FAILED: {exc}", file=sys.stderr)

    # Phase 3 — sources still on the old sync() contract run serially too.
    for source, mod in sync_only:
        settings = {**source.settings, "full": full}
        try:
            stats = mod.sync(db, settings, source.auth)
            print(f"[run] {source.name}: {stats}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[run] {source.name} FAILED: {exc}", file=sys.stderr)
    return failures


if __name__ == "__main__":
    main()
