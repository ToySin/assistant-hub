"""Jira ETL.

Pulls issues via the Jira Cloud REST API and loads them into the
workspace graph as JiraIssue / Person / Project nodes plus
assigned_to / belongs_to / blocked_by edges.

Auth: Basic auth with email + API token. The token comes from the
workspace's .env (`auth_env: JIRA_TOKEN` by default); the email is
read from JIRA_EMAIL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests
from surrealdb import RecordID, Surreal

from graph import builder
from library import monitor, search, sync_state

SOURCE_NAME = "jira"

DEFAULT_FIELDS = "summary,status,assignee,reporter,project,issuelinks,priority,issuetype,description,updated"
DEFAULT_JQL = "assignee = currentUser()"
PAGE_SIZE = 50


@dataclass
class SyncStats:
    issues: int = 0
    people: int = 0
    edges: int = 0


def sync(db: Surreal, settings: dict, auth: str) -> SyncStats:
    base_url = (settings.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ValueError("jira: base_url is required")

    email = os.environ.get("JIRA_EMAIL")
    if not email:
        raise ValueError("jira: JIRA_EMAIL not set in .env")

    project_keys = settings.get("project_keys") or []
    issue_scope = settings.get("scope") or "me"
    base_jql = settings.get("jql") or _default_jql(project_keys, scope=issue_scope)
    full = bool(settings.get("full"))

    # `scope` here = sync_state cache key, distinct from `issue_scope`.
    scope = f"{','.join(sorted(project_keys)) or '_all'}:{issue_scope}"
    since = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    started = sync_state.now_iso()

    jql = _add_delta(base_jql, since)
    issues = _fetch_issues(base_url, email, auth, jql)
    stats = _load_issues(db, issues, scope=scope)
    sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


ME_CLAUSE = (
    "(assignee = currentUser() "
    "OR reporter = currentUser() "
    "OR watcher = currentUser())"
)


def _default_jql(project_keys: list[str], scope: str = "me") -> str:
    """Build a default JQL.

    `scope`:
      - "me"  (default): only issues this user is involved in
        (assignee / reporter / watcher). Intersects with project_keys
        when given. This is what hub does — keeps the graph focused
        on the operator's actual work.
      - "all": every issue in the listed projects. Use only when you
        explicitly want the whole project's history (analytics, search).
    """
    if scope not in ("me", "all"):
        raise ValueError(f"jira: scope must be 'me' or 'all', got {scope!r}")

    if not project_keys:
        return ME_CLAUSE if scope == "me" else "ORDER BY updated DESC"

    # Quote each key — JQL parser otherwise confuses bare keys like 'IN'
    # with the IN operator.
    keys = ",".join(f'"{k}"' for k in project_keys)
    project_clause = f"project in ({keys})"
    if scope == "me":
        return f"{project_clause} AND {ME_CLAUSE}"
    return project_clause


def _add_delta(jql: str, since: str | None) -> str:
    """Wrap user JQL with `updated >= "<since>"` and a stable ORDER BY.

    JQL `updated` accepts ISO timestamps. We append rather than parse the
    user's JQL so any ORDER BY / extra clauses they wrote stay intact.
    """
    parts = []
    if since:
        parts.append(f'updated >= "{since}"')
    if jql:
        parts.append(f"({jql})")
    body = " AND ".join(parts) if parts else "ORDER BY updated DESC"
    if "ORDER BY" not in body.upper():
        body += " ORDER BY updated DESC"
    return body


def _fetch_issues(base_url: str, email: str, token: str, jql: str) -> list[dict]:
    """Atlassian deprecated /rest/api/3/search in early 2025 (returns 410).
    The replacement is /rest/api/3/search/jql with token-based pagination —
    no `total`, just `nextPageToken` until `isLast` is true."""
    url = f"{base_url}/rest/api/3/search/jql"
    auth = (email, token)
    headers = {"Accept": "application/json"}
    out: list[dict] = []
    next_token: str | None = None
    while True:
        params: dict = {
            "jql": jql,
            "fields": DEFAULT_FIELDS,
            "maxResults": PAGE_SIZE,
        }
        if next_token:
            params["nextPageToken"] = next_token
        r = requests.get(url, params=params, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        page = body.get("issues") or []
        out.extend(page)
        next_token = body.get("nextPageToken")
        if body.get("isLast") or not next_token or not page:
            break
    return out


def _load_issues(db: Surreal, issues: list[dict],
                 scope: str = "_all") -> SyncStats:
    stats = SyncStats()
    docs: list[dict] = []
    for issue in issues:
        f = issue.get("fields", {}) or {}
        key = issue["key"]
        project_key = _safe(f, "project", "key")
        project_name = _safe(f, "project", "name") or project_key

        if project_key:
            builder.upsert_project(db, key=project_key, name=project_name)

        new_title = _safe(f, "summary")
        new_status = _safe(f, "status", "name")
        prior = monitor.read_issue_state(db, "jira", key)
        issue_id = builder.upsert_issue(
            db,
            source="jira",
            external_key=key,
            title=new_title,
            status=new_status,
            body=_extract_description(f.get("description")),
        )
        monitor.emit_issue_diff(
            SOURCE_NAME, scope, key, prior,
            {"title": new_title, "status": new_status},
        )
        stats.issues += 1

        # Tear down only edges this sync controls — assignee changes,
        # blocks-link reshuffles, and project moves all need stale edges
        # cleared before the new ones land.
        _teardown_for_issue(db, issue_id)

        if project_key:
            project_id = builder.upsert_project(db, key=project_key, name=project_name)
            builder.relate(db, issue_id, "belongs_to", project_id)
            stats.edges += 1

        for role_field, edge in (("assignee", "assigned_to"),):
            person_name = _safe(f, role_field, "displayName")
            if person_name:
                person_id = builder.upsert_person(db, person_name)
                builder.relate(db, person_id, edge, issue_id)
                stats.people += 1
                stats.edges += 1

        for link in f.get("issuelinks") or []:
            link_type = (_safe(link, "type", "name") or "").lower()
            if link_type != "blocks":
                continue
            outward = _safe(link, "outwardIssue", "key")
            inward = _safe(link, "inwardIssue", "key")
            if outward:
                # Current issue blocks `outward`: outward is blocked_by current.
                stub = builder.ensure_issue(db, source="jira", external_key=outward)
                builder.relate(db, stub, "blocked_by", issue_id)
                stats.edges += 1
            if inward:
                # Current issue is blocked by `inward`.
                stub = builder.ensure_issue(db, source="jira", external_key=inward)
                builder.relate(db, issue_id, "blocked_by", stub)
                stats.edges += 1

        docs.append({
            "source": "jira",
            "external_id": key,
            "title": _safe(f, "summary"),
            "body": _extract_description(f.get("description")) or "",
            "author": _safe(f, "reporter", "displayName"),
            "url": f"{issue.get('self', '').rsplit('/rest/api/', 1)[0]}/browse/{key}"
                   if issue.get("self") else "",
            "updated_at": _safe(f, "updated"),
        })

    search.upsert_documents(docs)
    return stats


def _teardown_for_issue(db: Surreal, issue_id: RecordID) -> None:
    """Drop edges this issue's sync would re-create.

    `blocked_by` is bidirectional — when X is in the JQL window, this
    issue's sync writes both `X -> blocked_by -> Y` and `Y -> blocked_by
    -> X`. Both sides need to clear here so a removed link doesn't leave
    a stale edge behind.
    """
    db.query("DELETE belongs_to WHERE in = $i;", {"i": issue_id})
    db.query("DELETE assigned_to WHERE out = $i;", {"i": issue_id})
    db.query("DELETE blocked_by WHERE in = $i OR out = $i;", {"i": issue_id})


def _safe(obj: dict | None, *keys: str, default: str = "") -> str:
    cur: object = obj or {}
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k, {})
        else:
            return default
    return cur if isinstance(cur, str) else default


def _extract_description(adf: object) -> str | None:
    """Walk Atlassian Document Format to recover plain text. Returns None
    when the description is empty/missing."""
    if not adf:
        return None
    if isinstance(adf, str):
        return adf or None
    if not isinstance(adf, dict):
        return None
    chunks: list[str] = []
    _walk_adf(adf, chunks)
    text = "\n".join(c for c in chunks if c).strip()
    return text or None


def _walk_adf(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
        for child in node.get("content") or []:
            _walk_adf(child, out)
        if node.get("type") in ("paragraph", "heading", "listItem"):
            out.append("")
    elif isinstance(node, list):
        for child in node:
            _walk_adf(child, out)
