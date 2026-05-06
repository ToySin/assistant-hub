"""Workspace assessment + prioritization.

Reads the graph (Issues + their blocker / PR relationships) and ranks
each open item P0–P3 with a short reason. Intended to run after
`/briefing`: briefing answers "what's the state?", act answers "what
should I tackle and why?".

The scoring rules are deliberately graph-driven so they keep working
when more data flows in (assignees, statuses, PRs implementing
issues). With thin data they just collapse to "P2 — open backlog".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from graph import builder

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

CLOSED_STATUSES = {"closed", "done", "resolved", "complete", "completed"}


@dataclass
class Recommendation:
    source: str
    external_key: str
    title: str
    status: str
    priority: str        # P0 / P1 / P2 / P3
    reasons: list[str] = field(default_factory=list)


@dataclass
class Assessment:
    workspace: str
    recommendations: list[Recommendation]


def assess(workspace: str | None = None) -> Assessment:
    db = builder.connect(workspace)
    rows = db.query(
        """
        SELECT
            source, external_key, title, status,
            ->blocked_by->Issue.external_key AS blocked_by,
            <-blocked_by<-Issue.external_key AS blocks,
            <-implements<-GitHubPR.uid       AS prs
        FROM Issue;
        """
    )

    recs: list[Recommendation] = []
    for row in rows:
        status = (row.get("status") or "").lower()
        if status in CLOSED_STATUSES:
            continue
        priority, reasons = _classify(row)
        recs.append(Recommendation(
            source=row.get("source") or "?",
            external_key=row.get("external_key") or "?",
            title=row.get("title") or "",
            status=row.get("status") or "",
            priority=priority,
            reasons=reasons,
        ))

    recs.sort(key=lambda r: (PRIORITY_ORDER[r.priority], r.external_key))

    workspace_name = workspace or _infer_workspace_name()
    return Assessment(workspace=workspace_name, recommendations=recs)


def _classify(row: dict) -> tuple[str, list[str]]:
    """Pick a priority bucket from graph signals.

    Order matters: blocked_by short-circuits to P3 because acting on a
    blocked item is wasted effort. Otherwise blocking-others wins (P0)
    because unblocking cascades. Then in-flight signals (PR exists or
    status reads as in-progress/review) drop to P1. Default P2.
    """
    blocked_by = [k for k in (row.get("blocked_by") or []) if k]
    blocks = [k for k in (row.get("blocks") or []) if k]
    prs = [u for u in (row.get("prs") or []) if u]
    status = (row.get("status") or "").lower()

    if blocked_by:
        return "P3", [f"blocked by {', '.join(blocked_by)} — wait or unblock first"]

    if blocks:
        return "P0", [f"blocks {len(blocks)} downstream item(s): {', '.join(blocks)}"]

    if prs:
        return "P1", [f"PR in flight: {', '.join(prs)} — review/merge"]

    if "progress" in status or "review" in status:
        return "P1", [f"status: {row.get('status')}"]

    return "P2", ["open, no special signal"]


def _infer_workspace_name() -> str:
    try:
        from library.workspace import get_active_workspace
        return get_active_workspace()
    except Exception:  # noqa: BLE001
        return ""


def format_text(a: Assessment) -> str:
    lines: list[str] = [f"# Act — workspace: {a.workspace}", ""]
    if not a.recommendations:
        lines += ["No open items. Briefing-clean.", ""]
        return "\n".join(lines)

    by_priority: dict[str, list[Recommendation]] = {}
    for rec in a.recommendations:
        by_priority.setdefault(rec.priority, []).append(rec)

    for priority in ("P0", "P1", "P2", "P3"):
        bucket = by_priority.get(priority) or []
        if not bucket:
            continue
        lines.append(f"## {priority} ({_priority_blurb(priority)}) — {len(bucket)}")
        for rec in bucket:
            lines.append(f"- [{rec.source}] {rec.external_key} ({rec.status}) — {rec.title}")
            for reason in rec.reasons:
                lines.append(f"    {reason}")
        lines.append("")
    return "\n".join(lines)


def _priority_blurb(priority: str) -> str:
    return {
        "P0": "unblockers — do first",
        "P1": "in flight — finish",
        "P2": "open backlog",
        "P3": "blocked — wait",
    }[priority]


def main() -> None:
    print(format_text(assess()))


if __name__ == "__main__":
    main()
