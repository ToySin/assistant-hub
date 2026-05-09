"""Confluence ETL.

Pulls pages from configured spaces (and individual page ids) via the
Confluence Cloud REST API, converts each page's storage-format body
to plain text with markdown-ish structure, and loads each as a Note
in the workspace graph. L2 enrichment then extracts action items
(notably Confluence's `<ac:task>` elements, preserved as `- [ ]` /
`- [x]` checkboxes) into Issue nodes linked back via extracted_from.

Auth: Basic auth, email + API token. Reads `CONFLUENCE_EMAIL` first
and falls back to `JIRA_EMAIL` because Atlassian Cloud uses the same
account for both products. The API token comes from
`auth_env: CONFLUENCE_TOKEN` (sources.yaml default).

Delta-aware: each space sync uses CQL `lastmodified >= "<since>"` so
re-runs only fetch changed pages. `full: true` ignores the cursor.

Body conversion is intentionally lossy. We render headings, lists,
paragraphs, and `ac:task` checkboxes; everything else collapses to
plain text. Comments, attachments, and macro structure are dropped —
covering them properly is its own pass and would change the schema.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import unescape
from typing import Iterable

import requests
from surrealdb import Surreal

from graph import builder
from library import search, sync_state

SOURCE_NAME = "confluence"
PAGE_SIZE = 50
EXPAND = "body.storage,version,ancestors,space"


@dataclass
class SyncStats:
    pages: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str) -> SyncStats:
    base_url = (settings.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ValueError("confluence: base_url is required")
    spaces = settings.get("spaces") or []
    page_ids = settings.get("page_ids") or []
    # Page IDs to skip even when otherwise reachable via `spaces` — useful
    # when a single page contains content the workspace must not ingest
    # (leaked secrets, reviewer-flagged sensitive material). Coerce to
    # str so YAML int/str variants both match.
    exclude_page_ids = {str(p) for p in (settings.get("exclude_page_ids") or [])}
    if not spaces and not page_ids:
        raise ValueError(
            "confluence: at least one of `spaces` or `page_ids` is required"
        )

    email = os.environ.get("CONFLUENCE_EMAIL") or os.environ.get("JIRA_EMAIL")
    if not email:
        raise ValueError(
            "confluence: neither CONFLUENCE_EMAIL nor JIRA_EMAIL is set"
        )

    full = bool(settings.get("full"))
    scope = ",".join(sorted(list(spaces) + list(page_ids))) or "_all"
    since = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    started = sync_state.now_iso()

    auth_pair = (email, auth)
    stats = SyncStats()
    docs: list[dict] = []

    for space_key in spaces:
        for page in _list_space_pages(base_url, auth_pair, space_key, since):
            if str(page.get("id")) in exclude_page_ids:
                stats.skipped += 1
                continue
            _ingest(db, base_url, page, stats, docs)

    for page_id in page_ids:
        if str(page_id) in exclude_page_ids:
            stats.skipped += 1
            continue
        page = _get_page(base_url, auth_pair, page_id)
        if page is None:
            continue
        if since and (_modified(page) <= since):
            stats.skipped += 1
            continue
        _ingest(db, base_url, page, stats, docs)

    if docs:
        search.upsert_documents(docs)
    sync_state.set_(SOURCE_NAME, scope=scope, ts=started)
    return stats


# ---------- HTTP ----------

def _list_space_pages(
    base_url: str, auth: tuple[str, str], space_key: str, since: str | None,
) -> Iterable[dict]:
    """Yield every page in a space, optionally filtered by last-modified.

    Uses the search endpoint when `since` is set so the filter happens
    server-side; falls back to the content list endpoint for full
    syncs (search has hit a 1000-result ceiling historically).
    """
    if since:
        cql = f'type=page AND space="{space_key}" AND lastmodified >= "{_cql_date(since)}"'
        yield from _search_pages(base_url, auth, cql)
        return

    url = f"{base_url}/rest/api/content"
    params = {
        "spaceKey": space_key,
        "type": "page",
        "expand": EXPAND,
        "limit": PAGE_SIZE,
        "start": 0,
    }
    while True:
        r = requests.get(url, params=params, auth=auth, timeout=30)
        if r.status_code == 404:
            print(f"[confluence] space not found: {space_key}")
            return
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            yield page
        next_link = (data.get("_links") or {}).get("next")
        if not next_link:
            return
        params["start"] += params["limit"]


def _search_pages(
    base_url: str, auth: tuple[str, str], cql: str,
) -> Iterable[dict]:
    url = f"{base_url}/rest/api/content/search"
    params = {"cql": cql, "expand": EXPAND, "limit": PAGE_SIZE, "start": 0}
    while True:
        r = requests.get(url, params=params, auth=auth, timeout=30)
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            yield page
        if len(data.get("results", [])) < params["limit"]:
            return
        params["start"] += params["limit"]


def _get_page(
    base_url: str, auth: tuple[str, str], page_id: str,
) -> dict | None:
    r = requests.get(
        f"{base_url}/rest/api/content/{page_id}",
        params={"expand": EXPAND}, auth=auth, timeout=30,
    )
    if r.status_code == 404:
        print(f"[confluence] page not found: {page_id}")
        return None
    r.raise_for_status()
    return r.json()


def _cql_date(iso: str) -> str:
    """CQL accepts `"yyyy-MM-dd HH:mm"` for `lastmodified`. Convert ISO."""
    # iso e.g. 2026-05-07T16:30:00Z
    return iso.replace("T", " ").replace("Z", "").rsplit(":", 1)[0]


# ---------- Page → Note ----------

def _ingest(
    db: Surreal, base_url: str, page: dict,
    stats: SyncStats, docs: list[dict],
) -> None:
    page_id = str(page.get("id") or "")
    if not page_id:
        stats.skipped += 1
        return
    title = page.get("title") or "(untitled)"
    storage = (((page.get("body") or {}).get("storage") or {}).get("value") or "")
    body = storage_to_text(storage)
    modified_at = _modified(page)
    url = _page_url(base_url, page)

    builder.upsert_note(
        db,
        source=SOURCE_NAME,
        path=page_id,
        title=title,
        body=body,
        modified_at=modified_at,
    )
    stats.pages += 1
    docs.append({
        "source": SOURCE_NAME,
        "external_id": page_id,
        "title": title,
        "body": body or "",
        "author": (((page.get("version") or {}).get("by") or {}).get("displayName") or ""),
        "url": url,
        "updated_at": modified_at,
    })


def _modified(page: dict) -> str:
    return ((page.get("version") or {}).get("when")) or ""


def _page_url(base_url: str, page: dict) -> str:
    webui = (((page.get("_links") or {}).get("webui")) or "")
    if webui.startswith("/"):
        return base_url + webui
    return webui


# ---------- Storage format → plain text ----------

# Confluence storage format is XHTML-ish. We render only the parts the
# enrichment prompt cares about (headings, lists, task checkboxes,
# paragraphs) and strip the rest. Regex-based — fragile in theory but
# the storage format is mechanically generated and predictable enough
# for our purposes. If a page contains exotic macros that throw the
# parser off, the worst case is a slightly noisier body string for L2.

_TASK_RE = re.compile(
    r"<ac:task>(?P<head>.*?)<ac:task-body>(?P<body>.*?)</ac:task-body>(?P<tail>.*?)</ac:task>",
    re.DOTALL,
)
_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)
_BLOCK_BREAK_RE = re.compile(
    r"</p>|</div>|<br\s*/?>|</tr>|</h[1-6]>", re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def storage_to_text(html: str) -> str:
    if not html:
        return ""

    def task_sub(m: re.Match) -> str:
        complete = "<ac:task-status>complete</ac:task-status>" in m.group(0)
        body_inner = _TAG_RE.sub("", m.group("body"))
        body_inner = unescape(body_inner).strip()
        prefix = "- [x] " if complete else "- [ ] "
        return f"\n{prefix}{body_inner}\n"

    out = _TASK_RE.sub(task_sub, html)
    out = _HEADING_RE.sub(
        lambda m: f"\n{'#' * int(m.group(1))} {_strip(m.group(2))}\n", out
    )
    out = _LI_RE.sub(lambda m: f"\n- {_strip(m.group(1))}", out)
    out = _BLOCK_BREAK_RE.sub("\n", out)
    out = _TAG_RE.sub("", out)
    out = unescape(out)

    # Tidy whitespace.
    lines = [ln.rstrip() for ln in out.splitlines()]
    out = "\n".join(lines)
    out = _BLANK_RUN_RE.sub("\n\n", out)
    return out.strip()


def _strip(s: str) -> str:
    return _TAG_RE.sub("", s).strip()
