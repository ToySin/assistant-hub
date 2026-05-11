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
