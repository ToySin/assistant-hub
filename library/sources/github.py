"""GitHub ETL.

Pulls PRs through the `gh` CLI (already authenticated on the user's
machine) so we get auth + rate-limit handling for free without holding
yet another PAT.

Loads each PR as a GitHubPR node + the author as a Person + an
authored edge. Jira keys parsed from the PR title/body produce
implements edges.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from surrealdb import Surreal

from graph import builder
from graph.link_extractor import extract_jira_keys


@dataclass
class SyncStats:
    prs: int = 0
    people: int = 0
    edges: int = 0
    implements: int = 0


def sync(db: Surreal, settings: dict, auth: str | None = None) -> SyncStats:
    """`auth` is unused: gh handles its own auth. Kept for the uniform
    signature the orchestrator expects."""
    if not shutil.which("gh"):
        raise RuntimeError("github: `gh` CLI not found on PATH")

    repos = settings.get("repos") or []
    if not repos:
        raise ValueError("github: at least one repo (owner/repo) is required")
    state = "all"
    include_drafts = bool(settings.get("include_drafts"))
    limit = int(settings.get("limit") or 100)

    stats = SyncStats()
    for repo in repos:
        prs = _fetch_prs(repo, state=state, limit=limit)
        stats = _merge_stats(stats, _load_prs(db, repo, prs, include_drafts))
    return stats


def _fetch_prs(repo: str, *, state: str, limit: int) -> list[dict]:
    fields = "number,title,body,state,isDraft,author,url,headRefName"
    cmd = [
        "gh", "pr", "list",
        "--repo", repo,
        "--state", state,
        "--limit", str(limit),
        "--json", fields,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout) or []


def _load_prs(db: Surreal, repo: str, prs: list[dict], include_drafts: bool) -> SyncStats:
    stats = SyncStats()
    for pr in prs:
        if pr.get("isDraft") and not include_drafts:
            continue
        number = pr["number"]
        uid = f"{repo}#{number}"
        pr_id = builder.upsert_github_pr(
            db,
            uid=uid,
            title=pr.get("title") or "",
            state=(pr.get("state") or "").lower(),
        )
        stats.prs += 1

        author = (pr.get("author") or {}).get("login")
        if author:
            person_id = builder.upsert_person(db, author)
            builder.relate(db, person_id, "authored", pr_id)
            stats.people += 1
            stats.edges += 1

        text = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
        for jira_key in extract_jira_keys(text):
            issue_id = builder.ensure_issue(db, source="jira", external_key=jira_key)
            builder.relate(db, pr_id, "implements", issue_id)
            stats.implements += 1
            stats.edges += 1
    return stats


def _merge_stats(a: SyncStats, b: SyncStats) -> SyncStats:
    return SyncStats(
        prs=a.prs + b.prs,
        people=a.people + b.people,
        edges=a.edges + b.edges,
        implements=a.implements + b.implements,
    )
