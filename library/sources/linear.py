"""Linear ETL.

Pulls issues from configured teams via the Linear GraphQL API and loads
each as an Issue node in the workspace graph. Same table as Jira — the
`source` field distinguishes them. /briefing and /act work across both
because they filter on `status_category`, not source.

Auth: `LINEAR_API_KEY` — Personal API key from
  linear.app → Settings → Account → API → Personal API keys.

Delta: `updatedAt >= since` filter in the GraphQL query, cursor-paginated.
`full: true` ignores the cursor and re-fetches from the beginning.

Status mapping (Linear state.type → status_category):
  triage / backlog / unstarted → new
  started                      → indeterminate
  completed / canceled         → done

Graph model per issue:
  Issue node (source="linear", external_key="<TEAM>-<NUMBER>")
  assigned_to edge  → Person (by assignee.displayName or email)
  belongs_to edge   → Project (by Linear project.id + name)
  blocked_by edge   → Issue (via Linear relations of type blocks/blocked_by)

Settings (sources.yaml):
  team_keys: []        list of team keys (e.g. ["ENG", "INFRA"])
  full:      false     re-fetch everything ignoring cursor
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from surrealdb import Surreal

from graph import builder
from library import sync_state

SOURCE_NAME = "linear"
GRAPHQL_URL = "https://api.linear.app/graphql"
PAGE_SIZE = 250

_STATUS_MAP = {
    "triage": "new",
    "backlog": "new",
    "unstarted": "new",
    "started": "indeterminate",
    "completed": "done",
    "canceled": "done",
}

_ISSUES_QUERY = """
query Issues($filter: IssueFilter, $first: Int, $after: String) {
  issues(filter: $filter, first: $first, after: $after, orderBy: updatedAt) {
    nodes {
      id
      identifier
      title
      description
      state { name type }
      assignee { id email displayName }
      project { id name }
      relations {
        nodes {
          type
          relatedIssue { identifier }
        }
      }
      updatedAt
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


@dataclass
class SyncStats:
    issues: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str) -> SyncStats:
    if not auth:
        raise ValueError("linear: LINEAR_API_KEY is required (auth_env: LINEAR_API_KEY)")
    team_keys = settings.get("team_keys") or []
    if not team_keys:
        raise ValueError("linear: at least one entry in `team_keys` is required")

    full = bool(settings.get("full"))
    scope = ",".join(sorted(team_keys))
    since = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    started = sync_state.now_iso()

    hdrs = {"Authorization": auth, "Content-Type": "application/json"}
    stats = SyncStats()

    for issue in _iter_issues(hdrs, team_keys, since):
        _ingest(db, issue, stats)

    sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


# ---------- GraphQL iteration ----------

def _iter_issues(hdrs: dict, team_keys: list[str], since: str | None):
    gql_filter: dict[str, Any] = {
        "team": {"key": {"in": team_keys}},
    }
    if since:
        gql_filter["updatedAt"] = {"gte": since}

    cursor: str | None = None
    while True:
        variables: dict[str, Any] = {
            "filter": gql_filter,
            "first": PAGE_SIZE,
        }
        if cursor:
            variables["after"] = cursor

        r = requests.post(
            GRAPHQL_URL,
            headers=hdrs,
            json={"query": _ISSUES_QUERY, "variables": variables},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        errors = data.get("errors")
        if errors:
            raise RuntimeError(f"linear GraphQL error: {errors}")

        issues_data = data["data"]["issues"]
        yield from issues_data["nodes"]

        page_info = issues_data["pageInfo"]
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")


# ---------- Issue → graph ----------

def _ingest(db: Surreal, issue: dict, stats: SyncStats) -> None:
    identifier = issue.get("identifier") or ""
    if not identifier:
        stats.skipped += 1
        return

    state = issue.get("state") or {}
    status = state.get("name") or "Unknown"
    state_type = (state.get("type") or "").lower()
    status_category = _STATUS_MAP.get(state_type, "undefined")

    issue_id = builder.upsert_issue(
        db,
        source=SOURCE_NAME,
        external_key=identifier,
        title=issue.get("title") or "",
        status=status,
        status_category=status_category,
        body=issue.get("description"),
    )

    # Assignee
    assignee = issue.get("assignee")
    if assignee:
        name = assignee.get("displayName") or assignee.get("email") or ""
        if name:
            person_id = builder.upsert_person(db, name)
            builder.relate(db, person_id, "assigned_to", issue_id)

    # Project
    project = issue.get("project")
    if project:
        proj_id = builder.upsert_project(
            db,
            key=project["id"],
            name=project.get("name") or project["id"],
        )
        builder.relate(db, issue_id, "belongs_to", proj_id)

    # Blocker relations (deferred — we upsert stubs for referenced issues)
    for rel in ((issue.get("relations") or {}).get("nodes") or []):
        rel_type = (rel.get("type") or "").lower()
        related = (rel.get("relatedIssue") or {}).get("identifier") or ""
        if not related:
            continue
        related_id = builder.ensure_issue(db, source=SOURCE_NAME, external_key=related)
        if rel_type == "blocks":
            # this issue blocks the related one
            builder.relate(db, related_id, "blocked_by", issue_id)
        elif rel_type in ("blocked_by", "blocking"):
            builder.relate(db, issue_id, "blocked_by", related_id)

    stats.issues += 1
