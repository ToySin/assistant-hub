"""Markdown directories ETL.

Walks one or more directories, reads every `*.md` and `*.markdown` file,
parses optional YAML frontmatter, and loads each file as a Note node in
the workspace graph. Notes are not work items by themselves — L2
enrichment (`library.enrichment`) reads their bodies and extracts Issue
nodes (action items) linked back via `extracted_from`.

`paths` in sources.yaml is required; entries may be absolute or
home-relative. Hidden directories (`.git`, `.obsidian`, ...) are skipped.

Delta-aware: by default only files modified since the last sync are
re-processed. Pass `full: true` (or `--full` to the orchestrator) to
re-read everything.

No auth needed — markdown_dirs reads the local filesystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from surrealdb import Surreal

from graph import builder
from library import search, sync_state

SOURCE_NAME = "markdown_dirs"
EXTENSIONS = (".md", ".markdown")
SKIP_DIR_PREFIXES = (".",)  # .git, .obsidian, .venv, etc.


@dataclass
class SyncStats:
    notes: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str | None) -> SyncStats:
    raw_paths = settings.get("paths") or []
    if not raw_paths:
        raise ValueError("markdown_dirs: at least one entry in `paths` is required")

    paths = [_resolve(p) for p in raw_paths]
    for p in paths:
        if not p.is_dir():
            raise ValueError(f"markdown_dirs: path does not exist or is not a directory: {p}")

    full = bool(settings.get("full"))
    scope = ",".join(sorted(str(p) for p in paths))
    since = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    started = sync_state.now_iso()

    stats = SyncStats()
    docs: list[dict] = []
    for root in paths:
        for file_path in _walk(root):
            mtime_iso = _mtime_iso(file_path)
            if since and mtime_iso <= since:
                stats.skipped += 1
                continue
            try:
                title, body = _read(file_path)
            except OSError as exc:
                print(f"[markdown_dirs] skip {file_path}: {exc}")
                stats.skipped += 1
                continue
            note_id = builder.upsert_note(
                db,
                source=SOURCE_NAME,
                path=str(file_path),
                title=title,
                body=body,
                modified_at=mtime_iso,
            )
            # Wire inline Jira / PR refs in the note's body into
            # references_issue / references_pr edges so /briefing
            # can show "<note> -> SYS-123" connections without an LLM.
            builder.link_note_references(db, note_id, body)
            stats.notes += 1
            docs.append({
                "source": SOURCE_NAME,
                "external_id": str(file_path),
                "title": title,
                "body": body or "",
                "author": "",
                "url": file_path.as_uri(),
                "updated_at": mtime_iso,
            })

    if docs:
        search.upsert_documents(docs)

    sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


def _resolve(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not any(d.startswith(pref) for pref in SKIP_DIR_PREFIXES)
        ]
        for name in filenames:
            if name.lower().endswith(EXTENSIONS):
                yield Path(dirpath) / name


def _mtime_iso(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> tuple[str, str]:
    """Return (title, body). Frontmatter `title` wins; otherwise stem."""
    text = path.read_text(encoding="utf-8")
    front, body = _split_frontmatter(text)
    title = ""
    if isinstance(front, dict):
        title = str(front.get("title") or "").strip()
    if not title:
        title = path.stem
    return title, body


def _split_frontmatter(text: str) -> tuple[dict | None, str]:
    """Split YAML frontmatter delimited by `---` lines at the start of the file.
    Returns (frontmatter dict or None, body without frontmatter)."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines(keepends=True)
    if len(lines) < 2 or lines[0].rstrip() != "---":
        return None, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        return None, text
    front_block = "".join(lines[1:end])
    body = "".join(lines[end + 1:]).lstrip("\n")
    try:
        parsed = yaml.safe_load(front_block)
    except yaml.YAMLError:
        return None, text
    if not isinstance(parsed, dict):
        return None, text
    return parsed, body
