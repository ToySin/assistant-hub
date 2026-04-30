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


def upsert_issue(
    db: Surreal,
    source: str,
    external_key: str,
    title: str,
    status: str,
    body: str | None = None,
    embedding: list[float] | None = None,
) -> RecordID:
    """Upsert a tracked work item from any source. `source` is the origin
    system ('jira' or 'github'); `external_key` is that system's native
    identifier (e.g. 'SYS-123' or 'ToySin/repo#42'). The pair is unique."""
    thing_id = _issue_thing_id(source, external_key)
    res = db.query(
        """
        UPSERT type::thing('Issue', $thing_id)
        SET source = $source, external_key = $external_key,
            title = $title, status = $status,
            body = $body, embedding = $embedding
        RETURN id;
        """,
        {"thing_id": thing_id, "source": source, "external_key": external_key,
         "title": title, "status": status, "body": body, "embedding": embedding},
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
            title = '(stub)', status = 'Unknown'
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


def relate(
    db: Surreal,
    src: RecordID,
    edge: str,
    dst: RecordID,
    **props: Any,
) -> None:
    """Create an edge `src -> edge -> dst` with optional properties.

    Uses CONTENT for property assignment so callers do not build SurrealQL.
    """
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
