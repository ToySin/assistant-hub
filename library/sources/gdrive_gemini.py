"""Google Drive — Gemini meeting notes ETL.

Pulls auto-generated "Notes by Gemini" Google Doc files via the Drive
API, exports each as plain text, and indexes them into the workspace
search store. Auth piggybacks on `gcloud auth application-default
print-access-token` — no separate OAuth flow.

This is the LLM-meets-LLM bridge: Workspace AI's meeting transcripts
become first-class context the agent can `/search` later.

Settings (workspace `sources.yaml`):
  enabled         bool
  folder_ids      [str]  optional — limit to docs under these folders
                          (default: all drives the user can read)
  days_back       int    default 30 — how far back to look
  name_filter     str    default 'Notes by Gemini' — Drive name match
  max_files       int    default 50 — fetch cap per run
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from surrealdb import Surreal

from library import _gauth, search, sync_state

SOURCE_NAME = "gdrive_gemini"

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DEFAULT_NAME_FILTER = "Notes by Gemini"


@dataclass
class SyncStats:
    files: int = 0
    indexed: int = 0


def sync(db: Surreal, settings: dict, auth: str | None = None) -> SyncStats:
    """`db` is unused (we don't write graph nodes for v1) but stays in the
    signature so the orchestrator can dispatch us uniformly. `auth` is
    also unused — gcloud ADC supplies the bearer token."""
    name_filter = settings.get("name_filter") or DEFAULT_NAME_FILTER
    folder_ids = settings.get("folder_ids") or []
    days_back = int(settings.get("days_back") or 30)
    max_files = int(settings.get("max_files") or 50)
    full = bool(settings.get("full"))

    headers = _gauth.headers(auth)

    scope_key = ",".join(sorted(folder_ids)) or "_all"
    since_iso = None if full else sync_state.get(SOURCE_NAME, scope=scope_key)
    if since_iso:
        # Drive's `modifiedTime` operator wants an RFC 3339 timestamp.
        # We stored ISO-8601 UTC so it already qualifies.
        modified_after = since_iso
    else:
        modified_after = (datetime.now(timezone.utc) - timedelta(days=days_back)) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")

    started = sync_state.now_iso()
    files = _list_files(headers, name_filter, modified_after, folder_ids, max_files)
    stats = SyncStats(files=len(files))
    docs: list[dict] = []
    for f in files:
        text = _export_text(headers, f["id"])
        if not text:
            continue
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


def _list_files(headers: dict, name_filter: str, modified_after: str,
                folder_ids: list[str], max_files: int) -> list[dict]:
    """Walk Drive listing pages until we hit `max_files` or run out."""
    q_parts = [f"name contains '{name_filter}'",
               f"modifiedTime > '{modified_after}'",
               "trashed = false"]
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
                "gdrive_gemini: Drive API returned 403. Two common causes:\n"
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


def _export_text(headers: dict, file_id: str) -> str:
    r = requests.get(
        f"{DRIVE_FILES}/{file_id}/export",
        headers=headers,
        params={"mimeType": "text/plain"},
        timeout=60,
    )
    if r.status_code != 200:
        return ""
    return r.text
