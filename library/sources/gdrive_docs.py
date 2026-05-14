"""Google Drive — Docs / Slides / Sheets ETL.

Sibling to `gdrive_gemini` (which only ingests Gemini meeting notes).
This adapter pulls arbitrary Google Workspace authored content — design
docs, RFCs, spreadsheets, presentations — filtered by `mime_types`
rather than filename pattern.

Each file is exported as plain text and stored two ways:

- `Note` row in the graph (source='gdrive_docs'), so L2 enrichment +
  references_issue / mentions_person edges can attach to it
- search.documents row, so `/search` indexes the body via FTS5

Auth piggybacks on `gcloud auth application-default print-access-token`
— same path as gdrive_gemini, no separate OAuth flow.

Settings (workspace `sources.yaml`):
  enabled       bool
  folder_ids    [str]  optional — limit to docs under these folders
                       (default: all drives the user can read)
  mime_types    [str]  default: docs / slides / sheets
  days_back     int    default 30 — how far back to look
  max_files     int    default 100 — fetch cap per run
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from surrealdb import Surreal

from graph import builder
from library import _gauth, search, sync_state

SOURCE_NAME = "gdrive_docs"

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"

# Google Workspace mime types we know how to export to plain text.
DEFAULT_MIME_TYPES = [
    "application/vnd.google-apps.document",       # Docs
    "application/vnd.google-apps.presentation",   # Slides
    "application/vnd.google-apps.spreadsheet",    # Sheets
]

# Export targets per source mime type. Drive API requires we pick one
# per file — pick text/plain where available, csv for Sheets so cell
# content actually survives the export.
_EXPORT_MIMETYPE = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}


@dataclass
class SyncStats:
    files: int = 0
    notes: int = 0
    indexed: int = 0


def sync(db: Surreal, settings: dict, auth: str | None = None) -> SyncStats:
    """Bulk-ingest workspace Google Drive content. `auth` unused —
    gcloud ADC supplies the bearer token via `library._gauth`."""
    folder_ids = settings.get("folder_ids") or []
    mime_types = settings.get("mime_types") or list(DEFAULT_MIME_TYPES)
    days_back = int(settings.get("days_back") or 30)
    max_files = int(settings.get("max_files") or 100)
    full = bool(settings.get("full"))

    headers = _gauth.headers(auth)

    scope_key = ",".join(sorted(folder_ids + mime_types)) or "_all"
    since_iso = None if full else sync_state.get(SOURCE_NAME, scope=scope_key)
    if since_iso:
        modified_after = since_iso
    else:
        modified_after = (datetime.now(timezone.utc) - timedelta(days=days_back)) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")

    started = sync_state.now_iso()
    files = _list_files(headers, mime_types, modified_after, folder_ids, max_files)
    stats = SyncStats(files=len(files))
    docs: list[dict] = []

    for f in files:
        text = _export_text(headers, f["id"], f.get("mimeType", ""))
        if not text:
            continue

        # Note row in the graph — Drive file id is the canonical path so
        # re-ingests upsert in place rather than fanning out.
        builder.upsert_note(
            db,
            source=SOURCE_NAME,
            path=f["id"],
            title=f.get("name") or f["id"],
            body=text,
            modified_at=f.get("modifiedTime") or "",
        )
        stats.notes += 1

        docs.append({
            "source": SOURCE_NAME,
            "external_id": f["id"],
            "title": f.get("name", ""),
            "body": text,
            "url": f.get("webViewLink", ""),
            "updated_at": f.get("modifiedTime", ""),
        })

    if docs:
        search.upsert_documents(docs)
        stats.indexed = len(docs)
    sync_state.set_(SOURCE_NAME, scope=scope_key, ts=started)
    return stats


def _list_files(headers: dict, mime_types: list[str], modified_after: str,
                folder_ids: list[str], max_files: int) -> list[dict]:
    """Walk Drive listing pages until we hit `max_files` or run out."""
    mime_or = " or ".join(f"mimeType = '{mt}'" for mt in mime_types)
    q_parts = [
        f"({mime_or})",
        f"modifiedTime > '{modified_after}'",
        "trashed = false",
    ]
    if folder_ids:
        ors = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
        q_parts.append(f"({ors})")
    q = " and ".join(q_parts)

    out: list[dict] = []
    page_token: str | None = None
    while True:
        params = {
            "q": q,
            "fields": ("nextPageToken,"
                       "files(id,name,modifiedTime,webViewLink,mimeType)"),
            "orderBy": "modifiedTime desc",
            "pageSize": min(100, max_files - len(out)),
            "corpora": "allDrives",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(DRIVE_FILES, headers=headers, params=params, timeout=30)
        if r.status_code == 403:
            raise RuntimeError(
                "gdrive_docs: Drive API returned 403. Two common causes:\n"
                "  1. Drive API not enabled on the active gcloud project — "
                "enable it at console.cloud.google.com/apis/library/drive.googleapis.com "
                "and verify with `gcloud config get-value project`.\n"
                "  2. ADC token missing drive.readonly scope — re-login with "
                "`gcloud auth application-default login "
                "--scopes=openid,https://www.googleapis.com/auth/drive.readonly,"
                "https://www.googleapis.com/auth/cloud-platform`."
            )
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("files") or [])
        if len(out) >= max_files:
            return out[:max_files]
        page_token = body.get("nextPageToken")
        if not page_token:
            return out


def _export_text(headers: dict, file_id: str, mime_type: str) -> str:
    export_to = _EXPORT_MIMETYPE.get(mime_type, "text/plain")
    r = requests.get(
        f"{DRIVE_FILES}/{file_id}/export",
        headers=headers,
        params={"mimeType": export_to},
        timeout=60,
    )
    if r.status_code != 200:
        return ""
    return r.text
