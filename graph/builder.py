"""Graph builder: connection + schema apply + node/edge upserts.

Wraps SurrealDB so ETL code never writes raw SurrealQL strings.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from surrealdb import RecordID, Surreal

from library.workspace import get_workspace_path

SCHEMA_PATH = Path(__file__).parent / "schema.surql"

NAMESPACE = "workspace"
DATABASE = "graph"


def _db_dir(workspace: str | None = None) -> Path:
    return get_workspace_path(workspace) / "db" / "graph.surrealkv"


def connect(workspace: str | None = None) -> Surreal:
    """Open the workspace's embedded SurrealDB. Creates the directory if missing."""
    db_dir = _db_dir(workspace)
    db_dir.parent.mkdir(parents=True, exist_ok=True)
    db = Surreal(f"surrealkv://{db_dir}")
    db.use(NAMESPACE, DATABASE)
    return db


def apply_schema(db: Surreal) -> None:
    db.query(SCHEMA_PATH.read_text())


def upsert_person(db: Surreal, name: str) -> RecordID:
    """Upsert a person keyed by a stable slug of the display name so the same
    name produces the same RecordID across runs (required for diff-friendly
    exports)."""
    slug = _slugify(name)
    res = db.query(
        """
        UPSERT type::thing('Person', $slug)
        SET name = $name
        RETURN id;
        """,
        {"slug": slug, "name": name},
    )
    return _first_id(res)


def _issue_thing_id(source: str, external_key: str) -> str:
    return _slugify(f"{source}_{external_key}")


VALID_STATUS_CATEGORIES = {"new", "indeterminate", "done", "undefined"}


def upsert_issue(
    db: Surreal,
    source: str,
    external_key: str,
    title: str,
    status: str,
    status_category: str = "undefined",
    body: str | None = None,
    embedding: list[float] | None = None,
) -> RecordID:
    """Upsert a tracked work item from any source. `status` is the source's
    display label (often localized); `status_category` is Atlassian's
    universal vocabulary {new, indeterminate, done, undefined} used for
    filter logic so /briefing and /act work across languages."""
    if status_category not in VALID_STATUS_CATEGORIES:
        status_category = "undefined"
    thing_id = _issue_thing_id(source, external_key)
    res = db.query(
        """
        UPSERT type::thing('Issue', $thing_id)
        SET source = $source, external_key = $external_key,
            title = $title, status = $status,
            status_category = $status_category,
            body = $body, embedding = $embedding
        RETURN id;
        """,
        {"thing_id": thing_id, "source": source, "external_key": external_key,
         "title": title, "status": status, "status_category": status_category,
         "body": body, "embedding": embedding},
    )
    return _first_id(res)


def ensure_issue(db: Surreal, source: str, external_key: str) -> RecordID:
    """Return id of an existing Issue, or create a placeholder stub if
    none exists. Used when an issue is referenced before it has been
    fetched (e.g. a PR mentions a Jira key we have not loaded yet).
    Does not overwrite real data."""
    thing_id = _issue_thing_id(source, external_key)
    existing = db.query(
        "SELECT id FROM type::thing('Issue', $thing_id);",
        {"thing_id": thing_id},
    )
    if isinstance(existing, list) and existing:
        first = existing[0]
        if isinstance(first, list) and first:
            first = first[0]
        if isinstance(first, dict) and isinstance(first.get("id"), RecordID):
            return first["id"]
    res = db.query(
        """
        CREATE type::thing('Issue', $thing_id)
        SET source = $source, external_key = $external_key,
            title = '(stub)', status = 'Unknown',
            status_category = 'undefined'
        RETURN id;
        """,
        {"thing_id": thing_id, "source": source, "external_key": external_key},
    )
    return _first_id(res)


def upsert_github_pr(db: Surreal, uid: str, title: str, state: str) -> RecordID:
    res = db.query(
        """
        UPSERT type::thing('GitHubPR', $uid)
        SET uid = $uid, title = $title, state = $state
        RETURN id;
        """,
        {"uid": uid, "title": title, "state": state},
    )
    return _first_id(res)


def ensure_github_pr(db: Surreal, uid: str) -> RecordID:
    """Return id of an existing GitHubPR, or create a stub if none exists.

    Mirrors `ensure_issue`: used when a PR is referenced before its body
    has been fetched (e.g. a markdown note that mentions `owner/repo#42`).
    Doesn't overwrite real data."""
    existing = db.query(
        "SELECT id FROM type::thing('GitHubPR', $uid);", {"uid": uid},
    )
    found = _maybe_id(existing)
    if found is not None:
        return found
    res = db.query(
        """
        CREATE type::thing('GitHubPR', $uid)
        SET uid = $uid, title = '(stub)', state = 'unknown'
        RETURN id;
        """,
        {"uid": uid},
    )
    return _first_id(res)


def upsert_project(db: Surreal, key: str, name: str) -> RecordID:
    res = db.query(
        """
        UPSERT type::thing('Project', $key)
        SET key = $key, name = $name
        RETURN id;
        """,
        {"key": key, "name": name},
    )
    return _first_id(res)


def _note_thing_id(source: str, path: str) -> str:
    return _slugify(f"{source}_{path}")


def upsert_note(
    db: Surreal,
    source: str,
    path: str,
    title: str,
    body: str | None = None,
    modified_at: str | None = None,
) -> RecordID:
    """Upsert a Note (raw input — markdown file, Notion page, ...).

    Notes are not work items; they feed L2 enrichment which extracts
    Issue nodes from their bodies. `source` is the adapter name
    ('markdown_dirs', 'notion', 'obsidian'); `path` is whatever uniquely
    identifies the note inside that source (filesystem path, Notion id)."""
    thing_id = _note_thing_id(source, path)
    res = db.query(
        """
        UPSERT type::thing('Note', $thing_id)
        SET source = $source, path = $path, title = $title,
            body = $body, modified_at = $modified_at
        RETURN id;
        """,
        {"thing_id": thing_id, "source": source, "path": path,
         "title": title, "body": body, "modified_at": modified_at},
    )
    return _first_id(res)


def upsert_concept(db: Surreal, name: str) -> RecordID:
    slug = _slugify(name)
    res = db.query(
        """
        UPSERT type::thing('Concept', $slug)
        SET name = $name
        RETURN id;
        """,
        {"slug": slug, "name": name},
    )
    return _first_id(res)


def link_note_references(
    db: Surreal, note_id: RecordID, body: str | None,
    default_pr_repo: str | None = None,
) -> tuple[int, int]:
    """Scan a note's body for Jira keys and GitHub PR refs and create
    `references_issue` / `references_pr` edges accordingly. Targets are
    upserted as stubs via ensure_issue / ensure_github_pr if they aren't
    already in the graph.

    Returns (jira_count, pr_count). Safe to call on every ETL run —
    edges are idempotent via relate().
    """
    from graph.link_extractor import extract_jira_keys, extract_pr_refs

    jira_count = 0
    pr_count = 0
    if not body:
        return (jira_count, pr_count)

    for key in extract_jira_keys(body):
        issue_id = ensure_issue(db, source="jira", external_key=key)
        relate(db, note_id, "references_issue", issue_id)
        jira_count += 1

    for ref in extract_pr_refs(body, default_repo=default_pr_repo or ""):
        pr_id = ensure_github_pr(db, uid=ref)
        relate(db, note_id, "references_pr", pr_id)
        pr_count += 1

    return (jira_count, pr_count)


def delete_note(db: Surreal, source: str, path: str) -> None:
    """Delete a Note and all its outgoing/incoming edges.

    Used by ETL adapters when a source-side deletion is detected (e.g.
    a cancelled calendar event or a deleted Slack message).
    """
    thing_id = _note_thing_id(source, path)
    db.query(
        "DELETE type::thing('Note', $thing_id);",
        {"thing_id": thing_id},
    )


def relate_participation(
    db: Surreal,
    person_id: RecordID,
    note_id: RecordID,
    role: str | None = None,
) -> None:
    """Create a `participated_in` edge from a Person to a Note.

    Used for structured participation metadata from API sources (calendar
    attendees, Slack thread members, Gmail recipients) — more reliable
    than LLM-inferred `mentions_person` edges.
    """
    props = {"role": role} if role else {}
    relate(db, person_id, "participated_in", note_id, **props)


def relate(
    db: Surreal,
    src: RecordID,
    edge: str,
    dst: RecordID,
    **props: Any,
) -> None:
    """Create or update an edge `src -> edge -> dst`.

    Idempotent: if an edge with the same (in, out) on this table already
    exists, it is reused — properties are merged onto it instead of a
    duplicate edge being created. Without this, re-running ETL on an
    existing DB silently doubles every edge.
    """
    existing = db.query(
        f"SELECT id FROM {edge} WHERE in = $src AND out = $dst LIMIT 1;",
        {"src": src, "dst": dst},
    )
    edge_id = _maybe_id(existing)
    if edge_id is not None:
        if props:
            db.query("UPDATE $eid MERGE $props;",
                     {"eid": edge_id, "props": props})
        return

    if props:
        db.query(
            f"RELATE $src -> {edge} -> $dst CONTENT $props;",
            {"src": src, "dst": dst, "props": props},
        )
    else:
        db.query(
            f"RELATE $src -> {edge} -> $dst;",
            {"src": src, "dst": dst},
        )


def _maybe_id(res: Any) -> RecordID | None:
    if not isinstance(res, list) or not res:
        return None
    first = res[0]
    if isinstance(first, list) and first:
        first = first[0]
    if isinstance(first, dict) and isinstance(first.get("id"), RecordID):
        return first["id"]
    return None


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    """Lowercase, replace non-alphanumeric with underscore, strip ends.
    Falls back to a hash-like prefix if the result is empty."""
    slug = _SLUG_RE.sub("_", value.strip().lower()).strip("_")
    return slug or f"x{abs(hash(value)) % 10**8}"


def _first_id(res: Any) -> RecordID:
    """Extract the record ID from an UPSERT result.

    Keep the RecordID as an object — RELATE rejects stringified ids.
    """
    if isinstance(res, list) and res:
        first = res[0]
        if isinstance(first, list) and first:
            first = first[0]
        if isinstance(first, dict) and isinstance(first.get("id"), RecordID):
            return first["id"]
    raise RuntimeError(f"unexpected upsert result shape: {res!r}")
