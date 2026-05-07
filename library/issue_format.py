"""Shared rendering for Issue rows across briefing / act / search / etc.

Each source has its own idea of what's display-worthy:

- `jira`, `github_issues`: `external_key` is human-readable
  (`SYS-123`, `ToySin/repo#42`) so it goes in the line as-is.
- `note`: `external_key` is `<note_path>#<title-slug>` — a stable
  identity that's hostile to read. The useful label is the *source
  note's* title, fetched via the `extracted_from` edge. We surface
  that instead and drop the raw key.

Add new source rules here rather than scattering format conditionals
around the codebase.
"""

from __future__ import annotations


def format_issue_line(
    source: str | None,
    external_key: str | None,
    title: str | None,
    status: str | None,
    source_note: str | None = None,
) -> str:
    """Render a single Issue as a display line (no leading bullet)."""
    src = source or "?"
    t = title or ""
    st = status or ""

    if src == "note":
        origin = source_note or "(unknown note)"
        return f'[note] ({st}) {t}  ← from "{origin}"'

    key = external_key or "?"
    return f"[{src}] {key} ({st}) — {t}"


def pick_source_note(row: dict) -> str | None:
    """Pull a display name for the originating Note out of a query row
    that selected `->extracted_from->Note.title AS source_note_titles`.

    Note-derived Issues normally have exactly one source Note; if the
    list is empty we return None, if it has more than one we pick the
    first."""
    notes = row.get("source_note_titles")
    if not notes:
        return None
    if isinstance(notes, list):
        return str(notes[0]) if notes else None
    return str(notes)
