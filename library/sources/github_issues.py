"""GitHub Issues ETL.

Pulls issues through the `gh` CLI (auth + rate-limit handled by gh).
Loads each issue as an Issue node with source='github' plus the
author/assignee as Person nodes, the repo as a Project, and the
matching belongs_to / assigned_to edges.

Jira keys parsed out of the issue body produce Issue→Issue mention
links *via the L2 mentions pipeline* — not handled here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from surrealdb import Surreal

from graph import builder


@dataclass
class SyncStats:
    issues: int = 0
    people: int = 0
    edges: int = 0


def sync(db: Surreal, settings: dict, auth: str | None = None) -> SyncStats:
    if not shutil.which("gh"):
        raise RuntimeError("github_issues: `gh` CLI not found on PATH")

    repos = settings.get("repos") or []
    if not repos:
        raise ValueError("github_issues: at least one repo (owner/repo) is required")
    state = settings.get("state") or "all"
    limit = int(settings.get("limit") or 200)

    stats = SyncStats()
    for repo in repos:
        issues = _fetch_issues(repo, state=state, limit=limit)
        merged = _load_issues(db, repo, issues)
        stats = _merge_stats(stats, merged)
    return stats


def _fetch_issues(repo: str, *, state: str, limit: int) -> list[dict]:
    fields = "number,title,body,state,author,assignees,url,labels"
    cmd = [
        "gh", "issue", "list",
        "--repo", repo,
        "--state", state,
        "--limit", str(limit),
        "--json", fields,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout) or []


def _load_issues(db: Surreal, repo: str, issues: list[dict]) -> SyncStats:
    stats = SyncStats()

    project_id = builder.upsert_project(db, key=repo, name=repo)

    for issue in issues:
        number = issue["number"]
        external_key = f"{repo}#{number}"

        issue_id = builder.upsert_issue(
            db,
            source="github",
            external_key=external_key,
            title=issue.get("title") or "",
            status=(issue.get("state") or "").lower(),
            body=issue.get("body") or None,
        )
        stats.issues += 1

        builder.relate(db, issue_id, "belongs_to", project_id)
        stats.edges += 1

        for assignee in issue.get("assignees") or []:
            login = (assignee or {}).get("login")
            if login:
                person_id = builder.upsert_person(db, login)
                builder.relate(db, person_id, "assigned_to", issue_id)
                stats.people += 1
                stats.edges += 1

    return stats


def _merge_stats(a: SyncStats, b: SyncStats) -> SyncStats:
    return SyncStats(
        issues=a.issues + b.issues,
        people=a.people + b.people,
        edges=a.edges + b.edges,
    )
