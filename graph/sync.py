"""Export/import the graph as text so it can sync via git instead of binary DB.

Each table dumps to one jsonl file under <workspace>/exports/graph/.
On import, schema is reapplied first, then rows are CREATEd / RELATEd.
"""

from __future__ import annotations

import json
from pathlib import Path

from surrealdb import RecordID, Surreal

from library.workspace import get_workspace_export_dir

NODE_TABLES = ("Person", "JiraIssue", "GitHubPR", "Project", "Concept")
EDGE_TABLES = (
    "assigned_to", "authored", "implements",
    "belongs_to", "blocked_by", "mentions",
)


def export(db: Surreal, workspace: str | None = None) -> Path:
    out_dir = get_workspace_export_dir(workspace) / "graph"
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in NODE_TABLES + EDGE_TABLES:
        rows = db.query(f"SELECT * FROM {table};")
        rows = _unwrap(rows)
        path = out_dir / f"{table}.jsonl"
        with path.open("w") as f:
            for row in rows:
                f.write(json.dumps(_serialize(row)) + "\n")
    return out_dir


def import_(db: Surreal, workspace: str | None = None) -> None:
    in_dir = get_workspace_export_dir(workspace) / "graph"
    if not in_dir.is_dir():
        raise FileNotFoundError(f"no export to import: {in_dir}")
    for table in NODE_TABLES:
        for row in _read_jsonl(in_dir / f"{table}.jsonl"):
            row_id = row.pop("id")
            db.query(
                f"CREATE {row_id} CONTENT $data;",
                {"data": row},
            )
    for table in EDGE_TABLES:
        for row in _read_jsonl(in_dir / f"{table}.jsonl"):
            src = row.pop("in")
            dst = row.pop("out")
            row.pop("id", None)
            db.query(
                f"RELATE {src} -> {table} -> {dst} CONTENT $data;",
                {"data": row},
            )


def _unwrap(res: object) -> list[dict]:
    if isinstance(res, list) and res and isinstance(res[0], list):
        return res[0]
    if isinstance(res, list):
        return res
    return []


def _serialize(row: dict) -> dict:
    return {k: _to_jsonable(v) for k, v in row.items()}


def _to_jsonable(value: object) -> object:
    if isinstance(value, RecordID):
        return f"{value.table_name}:{value.id}"
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def _read_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
