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
from library.workspace import get_workspace_path


@dataclass
class Briefing:
    workspace: str
    dashboard: dict
    open_issues: list[dict] = field(default_factory=list)
    open_prs: list[dict] = field(default_factory=list)
    blocked_chains: list[dict] = field(default_factory=list)
    issue_counts_by_source: dict[str, int] = field(default_factory=dict)


def collect(workspace: str | None = None) -> Briefing:
    ws_path = get_workspace_path(workspace)
    dashboard = yaml.safe_load((ws_path / "dashboard.yaml").read_text()) or {}

    db = builder.connect(workspace)

    issue_rows = db.query(
        "SELECT source, external_key, title, status FROM Issue "
        "WHERE status NOT IN ['closed', 'Done', 'Resolved'] "
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

    return Briefing(
        workspace=dashboard.get("workspace") or (workspace or ""),
        dashboard=dashboard,
        open_issues=list(issue_rows),
        open_prs=list(pr_rows),
        blocked_chains=[r for r in blocked_rows if r.get("blockers")],
        issue_counts_by_source=counts,
    )


def format_text(b: Briefing) -> str:
    lines: list[str] = []
    lines.append(f"# Briefing — workspace: {b.workspace}")
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
            lines.append(f"- [{row['source']}] {row['external_key']} ({row['status']}) — {row['title']}")
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
    workspace = None
    if len(sys.argv) > 1 and sys.argv[1] == "--workspace":
        workspace = sys.argv[2]
    b = collect(workspace)
    print(format_text(b))


if __name__ == "__main__":
    main()
