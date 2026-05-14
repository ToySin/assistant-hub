"""Workspace briefing.

Reads dashboard.yaml + the workspace graph and prints a session-start
summary. Intended to be both a CLI (`python -m library.briefing`) and
the data-collection step for a future Claude skill that adds a
prioritization layer on top.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from graph import builder
from library import gcal, graph_queries, monitor
from library.issue_format import format_issue_line, pick_source_note
from library.workspace import get_workspace_path


@dataclass
class Briefing:
    workspace: str
    dashboard: dict
    open_issues: list[dict] = field(default_factory=list)
    open_prs: list[dict] = field(default_factory=list)
    blocked_chains: list[dict] = field(default_factory=list)
    dead_issues: list[graph_queries.DeadIssue] = field(default_factory=list)
    project_views: list[graph_queries.ProjectView] = field(default_factory=list)
    projects_yaml: list[dict] = field(default_factory=list)
    gh_notifications: list[dict] = field(default_factory=list)
    calendar_events: list[dict] = field(default_factory=list)
    issue_counts_by_source: dict[str, int] = field(default_factory=dict)
    recent_events: list[dict] = field(default_factory=list)


def _gh_current_user() -> str | None:
    """Return the logged-in gh user (best-effort, cached process-wide)."""
    import subprocess
    try:
        res = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None
    return None


def _split_prs_by_author(prs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into (authored-by-me, review-requested-from-me).

    The github source pulls PRs via `--author=@me` and `--review-requested=@me`
    and dedupes by url. So any PR in the result set is one or the other;
    where the user is the author, attribute it to the 'mine' bucket
    (takes precedence over self-review-requested edge cases)."""
    me = _gh_current_user()
    if not me:
        # No way to split — show everything in the 'mine' bucket so we
        # don't silently hide work.
        return list(prs), []
    mine: list[dict] = []
    review_req: list[dict] = []
    for pr in prs:
        authors = [a for a in (pr.get("authors") or []) if a]
        if me in authors:
            mine.append(pr)
        else:
            review_req.append(pr)
    return mine, review_req


def _filter_live_blockers(rows: list[dict]) -> list[dict]:
    """Drop rows where every blocker is already done. For the remainder,
    trim `blockers` to only the still-live (non-done) ones so display
    matches reality."""
    out: list[dict] = []
    for r in rows:
        blockers = r.get("blockers") or []
        cats = r.get("blocker_cats") or []
        live = [k for k, c in zip(blockers, cats) if k and c != "done"]
        if not live:
            continue
        out.append({**r, "blockers": live})
    return out


def collect(workspace: str | None = None) -> Briefing:
    ws_path = get_workspace_path(workspace)
    dashboard = yaml.safe_load((ws_path / "dashboard.yaml").read_text()) or {}

    db = builder.connect(workspace)

    # Filter by Atlassian's universal status_category (works across
    # locales / custom workflows). Skip stubs (undefined) — those are
    # cross-references from PRs we haven't fetched bodies for, not
    # actionable. Skip done. Keep new + indeterminate.
    # Sort 'indeterminate' (in progress / in review) above 'new' (backlog)
    # so actionable rows surface first — works out alphabetically since
    # 'i' < 'n'. Within a bucket, fall back to source + external_key for
    # stable ordering.
    issue_rows = db.query(
        "SELECT source, external_key, title, status, status_category, "
        "->extracted_from->Note.title AS source_note_titles "
        "FROM Issue "
        "WHERE status_category IN ['new', 'indeterminate'] "
        "ORDER BY status_category, source, external_key;"
    )

    # Also pull each PR's author so we can split "PRs I authored" from
    # "PRs I'm review-requested on". The github source pulls both via
    # `gh search prs --author=@me` + `--review-requested=@me`, deduped;
    # the author edge is the cleanest discriminator at display time.
    pr_rows = db.query(
        "SELECT uid, title, state, <-authored<-Person.name AS authors "
        "FROM GitHubPR WHERE state = 'open' ORDER BY uid;"
    )

    # Also fetch blocker status_category so done-blockers can be filtered
    # out — a chain like "PREM-1134 ← PREM-1132" is stale when 1132 is
    # already done (1134 is effectively unblocked).
    blocked_rows = db.query(
        "SELECT external_key, title, "
        "  ->blocked_by->Issue.external_key    AS blockers, "
        "  ->blocked_by->Issue.status_category AS blocker_cats "
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
        blocked_chains=_filter_live_blockers(blocked_rows),
        dead_issues=graph_queries.dead_issues(db),
        project_views=graph_queries.project_overview(db),
        projects_yaml=_load_projects_yaml(ws_path),
        gh_notifications=_fetch_gh_notifications(),
        calendar_events=gcal.today_events(days_ahead=1),
        issue_counts_by_source=counts,
        recent_events=recent_events,
    )


def _load_projects_yaml(ws_path: Path) -> list[dict]:
    """Read all *.yaml files under <workspace>/projects/."""
    projects_dir = ws_path / "projects"
    if not projects_dir.is_dir():
        return []
    result: list[dict] = []
    for f in sorted(projects_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
            if isinstance(data, dict):
                data["_file"] = f.name
                result.append(data)
        except Exception as exc:
            print(f"[briefing] skip {f.name}: {exc}")
    return result


def _fetch_gh_notifications() -> list[dict]:
    """Fetch participating GitHub notifications via gh CLI.

    Returns [] if gh is not installed or the call fails.
    """
    try:
        r = subprocess.run(
            [
                "gh", "api",
                "notifications?all=true&participating=true",
                "--jq",
                ".[] | {reason, repo: .repository.full_name, "
                "title: .subject.title, updated: .updated_at, "
                "url: .subject.url}",
            ],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return []
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        notifs: list[dict] = []
        for ln in lines:
            try:
                notifs.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return notifs
    except Exception:
        return []


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
        mine, review_requested = _split_prs_by_author(b.open_prs)
        if mine:
            lines.append(f"## My open PRs ({len(mine)})")
            for row in mine:
                lines.append(f"- {row['uid']} ({row['state']}) — {row['title']}")
            lines.append("")
        if review_requested:
            lines.append(f"## Review requested ({len(review_requested)})")
            for row in review_requested:
                authors = ", ".join(row.get("authors") or []) or "?"
                lines.append(
                    f"- {row['uid']} ({row['state']}) by {authors} — {row['title']}"
                )
            lines.append("")

    if b.blocked_chains:
        lines.append("## Blocked chains")
        for row in b.blocked_chains:
            blockers_str = ", ".join(row["blockers"])
            lines.append(
                f"- {row['external_key']} ({row['title']}) ← blocked by {blockers_str}"
            )
        lines.append("")

    if b.dead_issues:
        lines.append(f"## Orphan issues ({len(b.dead_issues)} — no PR, not blocking/blocked)")
        for d in b.dead_issues:
            lines.append(f"- [{d.source}] {d.external_key}: {d.title} ({d.status})")
        lines.append("")

    if b.project_views:
        lines.append("## Projects (graph)")
        for pv in b.project_views:
            pr_str = f", PRs: {', '.join(pv.pr_uids)}" if pv.pr_uids else ""
            lines.append(
                f"- {pv.name} ({pv.key}): {len(pv.open_issues)} open issue(s){pr_str}"
            )
        lines.append("")

    if b.projects_yaml:
        lines.append("## Project trackers (projects/*.yaml)")
        for proj in b.projects_yaml:
            name = proj.get("name") or proj.get("_file") or "(unnamed)"
            status = proj.get("status") or ""
            tasks = proj.get("tasks") or []
            open_tasks = [t for t in tasks if not t.get("done")]
            summary = f"{len(open_tasks)} open task(s)" if tasks else ""
            extra = ", ".join(filter(None, [status, summary]))
            lines.append(f"- {name}" + (f" — {extra}" if extra else ""))
        lines.append("")

    if b.gh_notifications:
        lines.append(f"## GitHub notifications ({len(b.gh_notifications)} participating)")
        by_repo: dict[str, list[dict]] = {}
        for n in b.gh_notifications:
            by_repo.setdefault(n.get("repo") or "unknown", []).append(n)
        for repo, notifs in sorted(by_repo.items()):
            lines.append(f"  {repo}:")
            for n in notifs[:5]:
                lines.append(f"    [{n.get('reason','')}] {n.get('title','')}")
            if len(notifs) > 5:
                lines.append(f"    ... +{len(notifs) - 5} more")
        lines.append("")

    if b.calendar_events:
        lines.append(f"## Today's schedule ({len(b.calendar_events)} event(s))")
        for ev in b.calendar_events:
            start = _fmt_time(ev.get("start") or "")
            lines.append(f"- {start} {ev.get('summary','')}" +
                         (f"  @ {ev['location']}" if ev.get("location") else ""))
        lines.append("")

    action_items = b.dashboard.get("action_items") or []
    if action_items:
        lines.append("## Action items (from dashboard)")
        for item in action_items:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)


def _fmt_time(iso: str) -> str:
    """Extract HH:MM from an ISO-8601 datetime string. Returns the raw
    string unchanged if it's a date-only value."""
    if "T" in iso:
        try:
            return iso.split("T")[1][:5]
        except IndexError:
            pass
    return iso


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Workspace session-start briefing.")
    parser.add_argument("--workspace", help="Override active workspace.")
    parser.add_argument("--no-timeline", action="store_true",
                        help="Suppress the 'Since last replay' section.")
    parser.add_argument("--no-gcal", action="store_true",
                        help="Skip Google Calendar fetch.")
    parser.add_argument("--no-gh-notifs", action="store_true",
                        help="Skip GitHub Notifications fetch.")
    parser.add_argument("--keep-cursor", action="store_true",
                        help="Don't advance the replay cursor — useful when "
                             "rendering the briefing twice in a row.")
    args = parser.parse_args()

    b = collect(args.workspace)
    if args.no_timeline:
        b.recent_events = []
    if args.no_gcal:
        b.calendar_events = []
    if args.no_gh_notifs:
        b.gh_notifications = []
    print(format_text(b))

    # Auto-advance the cursor once the briefing is rendered. The user has
    # now seen the timeline; nagging them on next run is the bug F2 fixed.
    if not args.keep_cursor and b.recent_events:
        monitor.mark_replayed(args.workspace)


if __name__ == "__main__":
    main()
