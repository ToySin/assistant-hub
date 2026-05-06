"""Local full-text search over Issue / PR text via SQLite FTS5.

Sidecar to the SurrealDB graph: the graph is for nodes/edges/embeddings,
the search index is for keyword queries on raw text. Each source's
ETL calls `upsert_documents()` after writing the graph node so the
two stores stay in sync.

Schema mirrors Hub's `search/search_tool/db.py` minus its per-source
convenience tables — we only keep the unified `documents` row + the
FTS5 virtual table backed by triggers. See issue #6 for the rationale
(SurrealDB FTS lacks Korean tokenization).

DB location: `<workspace>/db/search.db` (gitignored, regenerable).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from library.workspace import get_workspace_path

DB_FILENAME = "search.db"


def _db_path(workspace: str | None = None) -> Path:
    return get_workspace_path(workspace) / "db" / DB_FILENAME


@contextmanager
def _conn(workspace: str | None = None):
    path = _db_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title       TEXT DEFAULT '',
    body        TEXT DEFAULT '',
    author      TEXT DEFAULT '',
    url         TEXT DEFAULT '',
    updated_at  TEXT DEFAULT '',
    synced_at   TEXT DEFAULT (datetime('now')),
    metadata    TEXT DEFAULT '{}',
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_docs_source ON documents(source);
CREATE INDEX IF NOT EXISTS idx_docs_updated ON documents(updated_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, body, author,
    content=documents,
    content_rowid=id,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, body, author)
    VALUES (new.id, new.title, new.body, new.author);
END;

CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, body, author)
    VALUES ('delete', old.id, old.title, old.body, old.author);
END;

CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, body, author)
    VALUES ('delete', old.id, old.title, old.body, old.author);
    INSERT INTO documents_fts(rowid, title, body, author)
    VALUES (new.id, new.title, new.body, new.author);
END;
"""


def init(workspace: str | None = None) -> None:
    with _conn(workspace) as conn:
        conn.executescript(_SCHEMA)


def upsert_documents(docs: Iterable[dict], workspace: str | None = None) -> int:
    """Upsert documents keyed by (source, external_id). Returns how
    many were applied. Idempotent: re-running with the same content is
    a no-op other than refreshing `synced_at`."""
    rows = list(docs)
    if not rows:
        return 0
    init(workspace)
    with _conn(workspace) as conn:
        conn.executemany(
            """
            INSERT INTO documents
                (source, external_id, title, body, author, url,
                 updated_at, synced_at, metadata)
            VALUES (?,?,?,?,?,?,?, datetime('now'), ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                title=excluded.title, body=excluded.body,
                author=excluded.author, url=excluded.url,
                updated_at=excluded.updated_at,
                synced_at=datetime('now'), metadata=excluded.metadata
            """,
            [
                (
                    d["source"],
                    d["external_id"],
                    d.get("title", ""),
                    d.get("body", "") or "",
                    d.get("author", ""),
                    d.get("url", ""),
                    d.get("updated_at", ""),
                    json.dumps(d.get("metadata") or {}, ensure_ascii=False),
                )
                for d in rows
            ],
        )
    return len(rows)


def search(query: str, source: str | None = None, limit: int = 20,
           workspace: str | None = None) -> list[dict]:
    """Return matching documents ordered by FTS5 bm25 rank.

    `query` accepts FTS5 syntax (phrase searches with quotes, AND/OR,
    prefix `word*`). Bare words match across title/body/author."""
    init(workspace)
    sql = """
        SELECT d.id, d.source, d.external_id, d.title, d.body,
               d.author, d.url, d.updated_at, f.rank
        FROM documents_fts f
        JOIN documents d ON d.id = f.rowid
        WHERE documents_fts MATCH ?
    """
    params: list = [query]
    if source:
        sql += " AND d.source = ?"
        params.append(source)
    sql += " ORDER BY f.rank LIMIT ?"
    params.append(limit)
    with _conn(workspace) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def stats(workspace: str | None = None) -> list[dict]:
    init(workspace)
    with _conn(workspace) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT source, COUNT(*) AS count, MAX(synced_at) AS last_sync "
            "FROM documents GROUP BY source ORDER BY source"
        ).fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(prog="library.search",
                                     description="local FTS over indexed documents")
    sub = parser.add_subparsers(dest="cmd")

    p_q = sub.add_parser("q", help="run a query (default if no subcommand)")
    p_q.add_argument("query")
    p_q.add_argument("--source")
    p_q.add_argument("--limit", type=int, default=20)

    sub.add_parser("stats", help="show indexed-document counts per source")

    # Allow `python -m library.search "redis OOM"` — if the first arg
    # isn't a known subcommand, default to `q`.
    argv = sys.argv[1:]
    if not argv:
        parser.print_help()
        return 2
    if argv[0] not in {"q", "stats", "-h", "--help"}:
        argv = ["q", *argv]
    args = parser.parse_args(argv)

    if args.cmd == "stats":
        for row in stats():
            print(f"  {row['source']}: {row['count']} docs (last sync {row['last_sync']})")
        return 0

    if args.cmd == "q":
        results = search(args.query, source=args.source, limit=args.limit)
        if not results:
            print("(no matches)")
            return 0
        for r in results:
            print(f"[{r['source']}] {r['external_id']}  rank={r['rank']:.3f}")
            if r['title']:
                print(f"  {r['title']}")
            snippet = (r['body'] or "")[:160].replace("\n", " ")
            if snippet:
                print(f"  {snippet}{'...' if len(r['body'] or '') > 160 else ''}")
            if r['url']:
                print(f"  {r['url']}")
            print()
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
