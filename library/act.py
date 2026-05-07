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

import argparse
import subprocess
import sys
from dataclasses import dataclass, field

from graph import builder
from library import monitor, runbooks
from library.issue_format import format_issue_line, pick_source_note

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

CLOSED_STATUSES = {
    "closed", "done", "resolved", "complete", "completed",
    "stale",  # set by `enrichment --prune-stale` when an extracted action item
              # is no longer in the source note. Stale items shouldn't surface
              # in /act's priority queue.
}


@dataclass
class Recommendation:
    source: str
    external_key: str
    title: str
    status: str
    priority: str        # P0 / P1 / P2 / P3
    reasons: list[str] = field(default_factory=list)
    source_note: str | None = None    # for source='note', the originating Note's title


@dataclass
class RunbookProposal:
    """Pairing of a recent event with a runbook that matches its
    pattern. The level governs whether /act will execute it
    automatically or just surface it for human review."""
    event: dict
    runbook: runbooks.Runbook
    rendered: list[str]


@dataclass
class Assessment:
    workspace: str
    recommendations: list[Recommendation]
    proposals: list[RunbookProposal] = field(default_factory=list)


def assess(workspace: str | None = None) -> Assessment:
    db = builder.connect(workspace)
    rows = db.query(
        """
        SELECT
            source, external_key, title, status,
            ->blocked_by->Issue.external_key AS blocked_by,
            <-blocked_by<-Issue.external_key AS blocks,
            <-implements<-GitHubPR.uid       AS prs,
            ->extracted_from->Note.title     AS source_note_titles
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
            source_note=pick_source_note(row),
        ))

    recs.sort(key=lambda r: (PRIORITY_ORDER[r.priority], r.external_key))

    workspace_name = workspace or _infer_workspace_name()
    return Assessment(
        workspace=workspace_name,
        recommendations=recs,
        proposals=_runbook_proposals(workspace),
    )


def _runbook_proposals(workspace: str | None) -> list[RunbookProposal]:
    """For each recent event (since last replay), find matching runbooks
    and pre-render their commands. Auto-level proposals come first so
    `--execute` can act on them deterministically."""
    proposals: list[RunbookProposal] = []
    for event in monitor.since_last_replay(limit=50, workspace=workspace):
        for rb in runbooks.match_event(event, workspace=workspace):
            proposals.append(RunbookProposal(
                event=event,
                runbook=rb,
                rendered=[runbooks.render_step(s, event) for s in rb.steps],
            ))
    return proposals


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

    by_priority: dict[str, list[Recommendation]] = {}
    for rec in a.recommendations:
        by_priority.setdefault(rec.priority, []).append(rec)

    if not by_priority:
        lines += ["(no open items)", ""]
    for priority in ("P0", "P1", "P2", "P3"):
        bucket = by_priority.get(priority) or []
        if not bucket:
            continue
        lines.append(f"## {priority} ({_priority_blurb(priority)}) — {len(bucket)}")
        for rec in bucket:
            lines.append("- " + format_issue_line(
                rec.source, rec.external_key, rec.title, rec.status,
                source_note=rec.source_note,
            ))
            for reason in rec.reasons:
                lines.append(f"    {reason}")
        lines.append("")

    if a.proposals:
        lines.append(f"## Runbook proposals ({len(a.proposals)})")
        for p in a.proposals:
            mark = "AUTO" if p.runbook.automation_level == "auto" else \
                   "PROPOSE" if p.runbook.automation_level == "semi-auto" else "MANUAL"
            lines.append(f"- [{mark}] runbook #{p.runbook.id} '{p.runbook.name}' "
                         f"<- event #{p.event['id']} ({p.event['kind']} {p.event['subject_key']})")
            for cmd in p.rendered:
                lines.append(f"    $ {cmd}")
        lines.append("")
        lines.append("Run with `python -m library.act --execute` to fire AUTO proposals.")
        lines.append("")
    return "\n".join(lines)


def _priority_blurb(priority: str) -> str:
    return {
        "P0": "unblockers — do first",
        "P1": "in flight — finish",
        "P2": "open backlog",
        "P3": "blocked — wait",
    }[priority]


def execute_auto_proposals(a: Assessment,
                           workspace: str | None = None) -> int:
    """Run every AUTO-level proposal's commands, record outcome on the
    runbook, and emit an audit event. Returns the number of runbooks
    fired. Stops on the first failed step within a runbook (the rest
    don't run for that one — partial success would corrupt stats)."""
    fired = 0
    for p in a.proposals:
        if p.runbook.automation_level != "auto":
            continue
        outcome = "success"
        for cmd in p.rendered:
            print(f"[act] auto-running rb#{p.runbook.id}: $ {cmd}")
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.stdout:
                sys.stdout.write(res.stdout)
            if res.stderr:
                sys.stderr.write(res.stderr)
            if res.returncode != 0:
                outcome = "fail"
                break
        runbooks.record_outcome(p.runbook.id, outcome, workspace=workspace)
        monitor.emit(
            "act", "runbook", f"runbook.executed.{outcome}",
            f"rb#{p.runbook.id}",
            {"event_id": p.event["id"], "runbook_name": p.runbook.name},
            workspace=workspace,
        )
        fired += 1
    return fired


def main() -> None:
    parser = argparse.ArgumentParser(prog="library.act",
                                     description="prioritize + optionally fire runbooks")
    parser.add_argument("--execute", action="store_true",
                        help="Run AUTO-level runbook proposals (state-changing).")
    args = parser.parse_args()

    a = assess()
    print(format_text(a))
    if args.execute:
        fired = execute_auto_proposals(a)
        if fired:
            print(f"[act] fired {fired} AUTO runbook(s).")
        else:
            print("[act] no AUTO runbooks to fire.")


if __name__ == "__main__":
    main()
