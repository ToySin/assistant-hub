"""GitHub Issues ETL (delta-aware).

Pulls issues through the `gh` CLI (auth + rate-limit handled by gh).
Loads each issue as an Issue node with source='github' plus the
assignees as Person nodes, the repo as a Project, and the matching
belongs_to / assigned_to edges.

On re-run we fetch only issues `updated >= last_sync`. For each
fetched issue we tear down the edges this sync controls before
recreating them so assignee/state changes propagate cleanly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from surrealdb import RecordID, Surreal

from graph import builder
from library import monitor, search, sync_state

SOURCE_NAME = "github_issues"


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
    full = bool(settings.get("full"))

    stats = SyncStats()
    for repo in repos:
        since = None if full else sync_state.get(SOURCE_NAME, scope=repo)
        started = sync_state.now_iso()
        issues = _fetch_issues(repo, state=state, limit=limit, since=since)
        stats = _merge(stats, _load_issues(db, repo, issues))
        sync_state.set_(SOURCE_NAME, scope=repo, ts=started)
    return stats


def _fetch_issues(repo: str, *, state: str, limit: int,
                  since: str | None = None) -> list[dict]:
    fields = "number,title,body,state,author,assignees,url,labels,updatedAt"
    cmd = [
        "gh", "issue", "list",
        "--repo", repo,
        "--state", state,
        "--limit", str(limit),
        "--json", fields,
    ]
    if since:
        # gh search syntax accepts `updated:>=YYYY-MM-DD`. We trim to date
        # granularity to match what gh accepts; over-fetching by up to a
        # day is fine — the load step is idempotent.
        cmd.extend(["--search", f"updated:>={since[:10]}"])
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout) or []


def _load_issues(db: Surreal, repo: str, issues: list[dict]) -> SyncStats:
    stats = SyncStats()
    project_id = builder.upsert_project(db, key=repo, name=repo)
    docs: list[dict] = []

    for issue in issues:
        external_key = f"{repo}#{issue['number']}"
        new_title = issue.get("title") or ""
        new_status = (issue.get("state") or "").lower()

        prior = monitor.read_issue_state(db, "github", external_key)
        issue_id = builder.upsert_issue(
            db,
            source="github",
            external_key=external_key,
            title=new_title,
            status=new_status,
            body=issue.get("body") or None,
        )
        monitor.emit_issue_diff(
            SOURCE_NAME, repo, external_key, prior,
            {"title": new_title, "status": new_status},
        )
        stats.issues += 1

        # Tear down only the edges this sync controls so assignee/repo
        # changes propagate cleanly. Other sources' edges (e.g.
        # PR -implements-> issue) survive untouched.
        _teardown_for_issue(db, issue_id)

        builder.relate(db, issue_id, "belongs_to", project_id)
        stats.edges += 1

        for assignee in issue.get("assignees") or []:
            login = (assignee or {}).get("login")
            if login:
                person_id = builder.upsert_person(db, login)
                builder.relate(db, person_id, "assigned_to", issue_id)
                stats.people += 1
                stats.edges += 1

        docs.append({
            "source": "github",
            "external_id": external_key,
            "title": issue.get("title") or "",
            "body": issue.get("body") or "",
            "author": (issue.get("author") or {}).get("login", ""),
            "url": issue.get("url", ""),
        })

    search.upsert_documents(docs)
    return stats


def _teardown_for_issue(db: Surreal, issue_id: RecordID) -> None:
    db.query("DELETE belongs_to WHERE in = $i;", {"i": issue_id})
    db.query("DELETE assigned_to WHERE out = $i;", {"i": issue_id})


def _merge(a: SyncStats, b: SyncStats) -> SyncStats:
    return SyncStats(
        issues=a.issues + b.issues,
        people=a.people + b.people,
        edges=a.edges + b.edges,
    )
