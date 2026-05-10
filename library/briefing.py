"""Workspace briefing.

Reads dashboard.yaml + the workspace graph and prints a session-start
summary. Intended to be both a CLI (`python -m library.briefing`) and
the data-collection step for a future Claude skill that adds a
prioritization layer on top.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from graph import builder
from library import monitor
from library.issue_format import format_issue_line, pick_source_note
from library.workspace import get_workspace_path


@dataclass
class Briefing:
    workspace: str
    dashboard: dict
    open_issues: list[dict] = field(default_factory=list)
    open_prs: list[dict] = field(default_factory=list)
    blocked_chains: list[dict] = field(default_factory=list)
    issue_counts_by_source: dict[str, int] = field(default_factory=dict)
    recent_events: list[dict] = field(default_factory=list)


def collect(workspace: str | None = None) -> Briefing:
    ws_path = get_workspace_path(workspace)
    dashboard = yaml.safe_load((ws_path / "dashboard.yaml").read_text()) or {}

    db = builder.connect(workspace)

    # Filter by Atlassian's universal status_category (works across
    # locales / custom workflows). Skip stubs (undefined) — those are
    # cross-references from PRs we haven't fetched bodies for, not
    # actionable. Skip done. Keep new + indeterminate.
    issue_rows = db.query(
        "SELECT source, external_key, title, status, status_category, "
        "->extracted_from->Note.title AS source_note_titles "
        "FROM Issue "
        "WHERE status_category IN ['new', 'indeterminate'] "
        "ORDER BY source, external_key;"
    )

    pr_rows = db.query(
        "SELECT uid, title, state FROM GitHubPR WHERE state = 'open' ORDER BY uid;"
    )

    blocked_rows = db.query(
        "SELECT external_key, title, ->blocked_by->Issue.external_key AS blockers "
        "FROM Issue WHERE count(->blocked_by) > 0 ORDER BY external_key;"
    )

    counts: dict[str, int] = {}
    for row in issue_rows:
        counts[row["source"]] = counts.get(row["source"], 0) + 1

    recent_events = monitor.since_last_replay(limit=30, workspace=workspace)

    return Briefing(
        workspace=dashboard.get("workspace") or (workspace or ""),
        dashboard=dashboard,
        open_issues=list(issue_rows),
        open_prs=list(pr_rows),
        blocked_chains=[r for r in blocked_rows if r.get("blockers")],
        issue_counts_by_source=counts,
        recent_events=recent_events,
    )


def format_text(b: Briefing) -> str:
    lines: list[str] = []
    lines.append(f"# Briefing — workspace: {b.workspace}")
    lines.append("")

    if b.recent_events:
        lines.append(f"## Since last replay ({len(b.recent_events)})")
        for ev in b.recent_events[:15]:
            lines.append(f"- {ev['ts']}  {ev['kind']}  {ev['subject_key']}")
        if len(b.recent_events) > 15:
            lines.append(f"- ... +{len(b.recent_events) - 15} more")
        lines.append("")
        lines.append("(Cursor auto-advances on briefing exit. "
                     "Use `--keep-cursor` to disable, `--no-timeline` to skip this section.)")
        lines.append("")

    focus = b.dashboard.get("focus") or []
    if focus:
        lines.append("## Focus")
        for item in focus:
            lines.append(f"- {item}")
        lines.append("")

    blockers = b.dashboard.get("blockers") or []
    if blockers:
        lines.append("## Blockers (from dashboard)")
        for item in blockers:
            lines.append(f"- {item}")
        lines.append("")

    if b.issue_counts_by_source:
        summary = ", ".join(f"{k}: {v}" for k, v in sorted(b.issue_counts_by_source.items()))
        lines.append(f"## Open issues ({summary})")
        for row in b.open_issues:
            lines.append("- " + format_issue_line(
                row.get("source"), row.get("external_key"),
                row.get("title"), row.get("status"),
                source_note=pick_source_note(row),
            ))
        lines.append("")
    else:
        lines.append("## Open issues — none")
        lines.append("")

    if b.open_prs:
        lines.append(f"## Open PRs ({len(b.open_prs)})")
        for row in b.open_prs:
            lines.append(f"- {row['uid']} ({row['state']}) — {row['title']}")
        lines.append("")

    if b.blocked_chains:
        lines.append("## Blocked chains")
        for row in b.blocked_chains:
            blockers = ", ".join(row["blockers"])
            lines.append(f"- {row['external_key']} ({row['title']}) ← blocked by {blockers}")
        lines.append("")

    action_items = b.dashboard.get("action_items") or []
    if action_items:
        lines.append("## Action items (from dashboard)")
        for item in action_items:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Workspace session-start briefing.")
    parser.add_argument("--workspace", help="Override active workspace.")
    parser.add_argument("--no-timeline", action="store_true",
                        help="Suppress the 'Since last replay' section.")
    parser.add_argument("--keep-cursor", action="store_true",
                        help="Don't advance the replay cursor — useful when "
                             "rendering the briefing twice in a row.")
    args = parser.parse_args()

    b = collect(args.workspace)
    if args.no_timeline:
        b.recent_events = []
    print(format_text(b))

    # Auto-advance the cursor once the briefing is rendered. The user has
    # now seen the timeline; nagging them on next run is the bug F2 fixed.
    if not args.keep_cursor and b.recent_events:
        monitor.mark_replayed(args.workspace)


if __name__ == "__main__":
    main()
