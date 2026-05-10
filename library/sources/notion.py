"""Notion ETL.

Pulls pages from configured databases and standalone pages, walks
their block tree to recover plain-text bodies, and loads each page
as a Note in the workspace graph. Notes are not work items by
themselves — L2 enrichment (`library.enrichment`) reads them and
extracts action items as Issue nodes linked back via `extracted_from`.

Auth: Notion internal integration token. Reads `NOTION_TOKEN` from the
workspace's .env (sources.yaml default `auth_env`). The integration
must be explicitly shared with each database/page you want fetched —
that's Notion's security model, not a config thing on our side.

Delta-aware via `last_edited_time`. Set `full: true` (or pass `--full`
to the orchestrator) to ignore the cursor and re-fetch everything.

Block-to-text rules: most blocks become a single line of plain text.
Headings get `#` prefixes, list items get `- `, to-do blocks preserve
`- [ ]` / `- [x]` so the L2 prompt's checkbox heuristic still picks
them up as action items. Children are walked up to a small depth
limit; very deeply nested pages may be truncated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import requests
from surrealdb import Surreal

from graph import builder
from library import search, sync_state

SOURCE_NAME = "notion"
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
PAGE_SIZE = 100
MAX_BLOCK_DEPTH = 4


@dataclass
class SyncStats:
    pages: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str) -> SyncStats:
    db_ids = settings.get("database_ids") or []
    page_ids = settings.get("page_ids") or []
    if not db_ids and not page_ids:
        raise ValueError(
            "notion: at least one of database_ids or page_ids is required"
        )

    full = bool(settings.get("full"))
    scope = ",".join(sorted(list(db_ids) + list(page_ids))) or "_all"
    since = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    started = sync_state.now_iso()

    headers = _headers(auth)
    stats = SyncStats()
    docs: list[dict] = []

    for db_id in db_ids:
        for page in _query_database(db_id, headers, since):
            _ingest(db, page, headers, stats, docs)

    for page_id in page_ids:
        page = _get_page(page_id, headers)
        if page is None:
            continue
        if since and page.get("last_edited_time", "") <= since:
            stats.skipped += 1
            continue
        _ingest(db, page, headers, stats, docs)

    if docs:
        search.upsert_documents(docs)
    sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


# ---------- HTTP helpers ----------

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _query_database(
    db_id: str, headers: dict, since: str | None,
) -> Iterable[dict]:
    """Paginate through a database's pages, optionally filtered by
    last_edited_time. Yields page objects."""
    url = f"{API}/databases/{db_id}/query"
    body: dict = {"page_size": PAGE_SIZE}
    if since:
        body["filter"] = {
            "timestamp": "last_edited_time",
            "last_edited_time": {"after": since},
        }
    while True:
        r = requests.post(url, headers=headers, json=body, timeout=30)
        if r.status_code == 404:
            print(f"[notion] database not found or not shared: {db_id}")
            return
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            yield page
        if not data.get("has_more"):
            return
        body["start_cursor"] = data.get("next_cursor")


def _get_page(page_id: str, headers: dict) -> dict | None:
    r = requests.get(f"{API}/pages/{page_id}", headers=headers, timeout=30)
    if r.status_code == 404:
        print(f"[notion] page not found or not shared: {page_id}")
        return None
    r.raise_for_status()
    return r.json()


# ---------- Page → Note ----------

def _ingest(
    db: Surreal, page: dict, headers: dict,
    stats: SyncStats, docs: list[dict],
) -> None:
    page_id = page["id"]
    title = _extract_title(page)
    modified_at = page.get("last_edited_time", "")
    url = page.get("url", "")
    body = _extract_body(page_id, headers)

    note_id = builder.upsert_note(
        db,
        source=SOURCE_NAME,
        path=page_id,
        title=title,
        body=body,
        modified_at=modified_at,
    )
    builder.link_note_references(db, note_id, body)
    stats.pages += 1
    docs.append({
        "source": SOURCE_NAME,
        "external_id": page_id,
        "title": title,
        "body": body or "",
        "author": "",
        "url": url,
        "updated_at": modified_at,
    })


def _extract_title(page: dict) -> str:
    """Pull the title from page properties. Notion stores it under
    whichever property is title-typed (db pages) or under a fixed
    'title' key (standalone pages)."""
    props = page.get("properties", {}) or {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            arr = prop.get("title") or []
            text = "".join(t.get("plain_text", "") for t in arr).strip()
            if text:
                return text
    return "(untitled)"


def _extract_body(page_id: str, headers: dict) -> str:
    chunks: list[str] = []
    _walk_blocks(page_id, headers, chunks, depth=0)
    return "\n".join(c for c in chunks if c).strip()


def _walk_blocks(
    parent_id: str, headers: dict, out: list[str], depth: int,
) -> None:
    if depth > MAX_BLOCK_DEPTH:
        return
    url = f"{API}/blocks/{parent_id}/children"
    params = {"page_size": PAGE_SIZE}
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 404:
            return
        r.raise_for_status()
        data = r.json()
        for block in data.get("results", []):
            text = _block_to_text(block)
            if text:
                out.append(text)
            if block.get("has_children"):
                _walk_blocks(block["id"], headers, out, depth + 1)
        if not data.get("has_more"):
            return
        params["start_cursor"] = data.get("next_cursor")


def _block_to_text(block: dict) -> str:
    btype = block.get("type")
    if not btype:
        return ""
    payload = block.get(btype) or {}
    rich_text = payload.get("rich_text") or []
    text = "".join(t.get("plain_text", "") for t in rich_text)

    # Preserve checkbox markers so the enrichment prompt's `- [ ]` /
    # `- [x]` heuristic picks Notion to-do blocks up as action items.
    if btype == "to_do":
        prefix = "- [x] " if payload.get("checked") else "- [ ] "
        return prefix + text

    if btype in ("bulleted_list_item", "numbered_list_item"):
        return "- " + text

    if btype.startswith("heading_"):
        try:
            level = int(btype.split("_", 1)[1])
        except ValueError:
            level = 2
        return ("#" * max(1, min(level, 6))) + " " + text

    if btype == "quote":
        return "> " + text

    if btype == "code":
        lang = payload.get("language") or ""
        return f"```{lang}\n{text}\n```"

    return text
