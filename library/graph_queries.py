"""Graph query layer: higher-level read patterns over the SurrealDB graph.

Replaces hub's graph/trace.py (which targeted Neo4j). All queries are
read-only and safe to call from both briefing and act.

Three entry points:
  dead_issues(db)      — orphan backlog: open, no PR, not blocking/blocked
  blocked_chains(db)   — issues with blocked_by / blocks relationships
  project_overview(db) — per-project: open issue count + linked PRs
"""

from __future__ import annotations

from dataclasses import dataclass, field

from surrealdb import Surreal


@dataclass
class DeadIssue:
    source: str
    external_key: str
    title: str
    status: str
    status_category: str


@dataclass
class BlockedChain:
    source: str
    external_key: str
    title: str
    blocked_by: list[str]
    blocks: list[str] = field(default_factory=list)


@dataclass
class ProjectView:
    key: str
    name: str
    open_issues: list[dict] = field(default_factory=list)
    pr_uids: list[str] = field(default_factory=list)


def dead_issues(db: Surreal) -> list[DeadIssue]:
    """Open issues with no PR implementing them, not blocking anything,
    and not blocked by anything — the 'orphan backlog' signal."""
    rows = db.query(
        """
        SELECT source, external_key, title, status, status_category,
               ->blocked_by->Issue.external_key AS blocked_by,
               <-blocked_by<-Issue.external_key AS blocks,
               <-implements<-GitHubPR.uid        AS prs
        FROM Issue
        WHERE status_category IN ['new', 'indeterminate'];
        """
    )
    result: list[DeadIssue] = []
    for row in (rows or []):
        has_pr      = bool([u for u in (row.get("prs")        or []) if u])
        has_blocker = bool([k for k in (row.get("blocked_by") or []) if k])
        is_blocker  = bool([k for k in (row.get("blocks")     or []) if k])
        if has_pr or has_blocker or is_blocker:
            continue
        result.append(DeadIssue(
            source=row.get("source") or "?",
            external_key=row.get("external_key") or "?",
            title=row.get("title") or "",
            status=row.get("status") or "",
            status_category=row.get("status_category") or "undefined",
        ))
    return result


def blocked_chains(db: Surreal) -> list[BlockedChain]:
    """Issues that are blocked by other issues or that are blocking others."""
    rows = db.query(
        """
        SELECT source, external_key, title, status,
               ->blocked_by->Issue.external_key AS blocked_by,
               <-blocked_by<-Issue.external_key AS blocks
        FROM Issue
        WHERE status_category IN ['new', 'indeterminate'];
        """
    )
    result: list[BlockedChain] = []
    for row in (rows or []):
        bby = [k for k in (row.get("blocked_by") or []) if k]
        bks = [k for k in (row.get("blocks") or []) if k]
        if not bby and not bks:
            continue
        result.append(BlockedChain(
            source=row.get("source") or "?",
            external_key=row.get("external_key") or "?",
            title=row.get("title") or "",
            status=row.get("status") or "",
            blocked_by=bby,
            blocks=bks,
        ))
    return result


def project_overview(db: Surreal) -> list[ProjectView]:
    """For each Project with open issues: issue list + implementing PR UIDs."""
    proj_rows = db.query(
        """
        SELECT key, name,
               <-belongs_to<-Issue.{source, external_key, title, status, status_category}
               AS issues
        FROM Project;
        """
    )
    result: list[ProjectView] = []
    for proj in (proj_rows or []):
        open_issues = [
            i for i in (proj.get("issues") or [])
            if (i.get("status_category") or "undefined") in ("new", "indeterminate")
        ]
        if not open_issues:
            continue
        keys = [i["external_key"] for i in open_issues if i.get("external_key")]
        pr_uids: list[str] = []
        if keys:
            pr_rows = db.query(
                "SELECT uid FROM GitHubPR "
                "WHERE ->implements->Issue.external_key CONTAINSANY $keys;",
                {"keys": keys},
            )
            pr_uids = [r["uid"] for r in (pr_rows or []) if r.get("uid")]
        result.append(ProjectView(
            key=proj.get("key") or "",
            name=proj.get("name") or "",
            open_issues=open_issues,
            pr_uids=pr_uids,
        ))
    return result


@dataclass
class StakeholderView:
    name: str
    assigned_issues: list[dict] = field(default_factory=list)
    authored_prs: list[dict] = field(default_factory=list)


def stakeholders(db: Surreal, name: str) -> StakeholderView:
    """Find open issues assigned to `name` and PRs authored by them.

    Used by /act Step 3 context enrichment to understand who is involved
    in a work item and what else they're working on.
    """
    person_rows = db.query(
        "SELECT id FROM Person WHERE name = $name LIMIT 1;",
        {"name": name},
    )
    person_id = (person_rows[0].get("id") if person_rows else None)
    if not person_id:
        return StakeholderView(name=name)

    issue_rows = db.query(
        """
        SELECT source, external_key, title, status, status_category
        FROM Issue
        WHERE <-assigned_to<-Person.id CONTAINS $pid
          AND status_category IN ['new', 'indeterminate'];
        """,
        {"pid": person_id},
    )
    pr_rows = db.query(
        """
        SELECT uid, title, state FROM GitHubPR
        WHERE <-authored<-Person.id CONTAINS $pid AND state = 'open';
        """,
        {"pid": person_id},
    )
    return StakeholderView(
        name=name,
        assigned_issues=list(issue_rows or []),
        authored_prs=list(pr_rows or []),
    )


@dataclass
class TraceNode:
    source: str
    external_key: str
    title: str
    status: str
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    prs: list[str] = field(default_factory=list)


def trace(db: Surreal, external_key: str, depth: int = 2) -> list[TraceNode]:
    """Return the subgraph fan-out around `external_key` up to `depth` hops.

    Walks blocked_by in both directions and collects implementing PRs.
    Used by /act Step 3 to load all context around a specific issue before
    taking action (e.g. understanding the full blocker chain).
    """
    visited: set[str] = set()
    result: list[TraceNode] = []
    _trace_recurse(db, external_key, depth, visited, result)
    return result


def _trace_recurse(
    db: Surreal, key: str, depth: int,
    visited: set[str], result: list[TraceNode],
) -> None:
    if depth < 0 or key in visited:
        return
    visited.add(key)
    rows = db.query(
        """
        SELECT source, external_key, title, status,
               ->blocked_by->Issue.external_key AS blocked_by,
               <-blocked_by<-Issue.external_key AS blocks,
               <-implements<-GitHubPR.uid        AS prs
        FROM Issue WHERE external_key = $key LIMIT 1;
        """,
        {"key": key},
    )
    if not (rows or []):
        return
    row = rows[0]
    node = TraceNode(
        source=row.get("source") or "?",
        external_key=row.get("external_key") or key,
        title=row.get("title") or "",
        status=row.get("status") or "",
        blocked_by=[k for k in (row.get("blocked_by") or []) if k],
        blocks=[k for k in (row.get("blocks") or []) if k],
        prs=[u for u in (row.get("prs") or []) if u],
    )
    result.append(node)
    for neighbor in node.blocked_by + node.blocks:
        _trace_recurse(db, neighbor, depth - 1, visited, result)
