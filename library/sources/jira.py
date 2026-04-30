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
from surrealdb import Surreal

from graph import builder

DEFAULT_FIELDS = "summary,status,assignee,reporter,project,issuelinks,priority,issuetype,description"
DEFAULT_JQL = "assignee = currentUser() ORDER BY updated DESC"
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
    jql = settings.get("jql") or _default_jql(project_keys)

    issues = _fetch_issues(base_url, email, auth, jql)
    return _load_issues(db, issues)


def _default_jql(project_keys: list[str]) -> str:
    if not project_keys:
        return DEFAULT_JQL
    keys = ",".join(project_keys)
    return f"project IN ({keys}) ORDER BY updated DESC"


def _fetch_issues(base_url: str, email: str, token: str, jql: str) -> list[dict]:
    url = f"{base_url}/rest/api/3/search"
    auth = (email, token)
    headers = {"Accept": "application/json"}
    out: list[dict] = []
    start_at = 0
    while True:
        params = {
            "jql": jql,
            "fields": DEFAULT_FIELDS,
            "startAt": start_at,
            "maxResults": PAGE_SIZE,
        }
        r = requests.get(url, params=params, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        page = body.get("issues") or []
        out.extend(page)
        if len(out) >= body.get("total", 0) or not page:
            break
        start_at += len(page)
    return out


def _load_issues(db: Surreal, issues: list[dict]) -> SyncStats:
    stats = SyncStats()
    for issue in issues:
        f = issue.get("fields", {}) or {}
        key = issue["key"]
        project_key = _safe(f, "project", "key")
        project_name = _safe(f, "project", "name") or project_key

        if project_key:
            builder.upsert_project(db, key=project_key, name=project_name)

        issue_id = builder.upsert_jira_issue(
            db,
            key=key,
            title=_safe(f, "summary"),
            status=_safe(f, "status", "name"),
            body=_extract_description(f.get("description")),
        )
        stats.issues += 1

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
                stub = builder.ensure_jira_issue(db, key=outward)
                builder.relate(db, stub, "blocked_by", issue_id)
                stats.edges += 1
            if inward:
                # Current issue is blocked by `inward`.
                stub = builder.ensure_jira_issue(db, key=inward)
                builder.relate(db, issue_id, "blocked_by", stub)
                stats.edges += 1

    return stats


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
