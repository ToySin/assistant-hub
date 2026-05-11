"""Google Calendar ETL.

Fetches calendar events and stores them as Note nodes in the workspace
graph. Unlike library/gcal.py (which is a live briefing-time fetch that
requires google-api-python-client), this adapter talks directly to the
Calendar REST API via gcloud ADC — no extra Python packages needed.

Each event becomes a Note:
  source      = "gcal"
  path        = "<calendar_id>:<event_id>"
  title       = event.summary
  body        = description + attendee list + location + times
  modified_at = event.updated

Attendees become Person nodes linked via `participated_in` edges.
Jira keys + PR refs found in summary/description produce
`references_issue` / `references_pr` edges (same as markdown_dirs).

Cancelled events trigger deletion of the corresponding Note.

Auth: falls back to ADC via `library._gauth` when `auth` is not set.
If `auth_env: GOOGLE_OAUTH_TOKEN` is configured and the env var is
present, that token is used directly (skips the gcloud subprocess).

Delta: stores Google's syncToken in sync_state as 'tok:<value>'.
Falls back to a time-bounded initial fetch when no token exists or
after a 410 Gone (token expired — normal after ~14 days of inactivity).

Settings (sources.yaml):
  calendar_ids: ["primary"]   calendar IDs to fetch
  days_back:    7             initial seed: how far back
  days_ahead:   14            initial seed: how far forward
  full:         false         ignore syncToken and reseed
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from surrealdb import Surreal

from graph import builder
from library import _gauth, sync_state
from graph.link_extractor import extract_jira_keys, extract_pr_refs

SOURCE_NAME = "gcal"
CAL_BASE = "https://www.googleapis.com/calendar/v3"
PAGE_SIZE = 250


class _GoneError(Exception):
    pass


@dataclass
class SyncStats:
    events: int = 0
    deleted: int = 0
    skipped: int = 0


def sync(db: Surreal, settings: dict, auth: str | None = None) -> SyncStats:
    calendar_ids = settings.get("calendar_ids") or ["primary"]
    days_back = int(settings.get("days_back") or 7)
    days_ahead = int(settings.get("days_ahead") or 14)
    full = bool(settings.get("full"))
    hdrs = _gauth.headers(auth)

    stats = SyncStats()
    for cal_id in calendar_ids:
        _sync_calendar(db, hdrs, cal_id, days_back, days_ahead, full, stats)
    return stats


# ---------- Per-calendar sync ----------

def _sync_calendar(
    db: Surreal, hdrs: dict, cal_id: str,
    days_back: int, days_ahead: int, full: bool, stats: SyncStats,
) -> None:
    scope = f"cal:{cal_id}"
    raw_cursor = None if full else sync_state.get(SOURCE_NAME, scope=scope)
    sync_token: str | None = None
    if raw_cursor and raw_cursor.startswith("tok:"):
        sync_token = raw_cursor[4:]

    try:
        events, new_token = _fetch_events(hdrs, cal_id, sync_token, days_back, days_ahead)
    except _GoneError:
        # syncToken expired — clear cursor and reseed
        sync_state.set_(SOURCE_NAME, scope=scope, ts="")
        _sync_calendar(db, hdrs, cal_id, days_back, days_ahead, True, stats)
        return

    for event in events:
        if event.get("status") == "cancelled":
            builder.delete_note(db, SOURCE_NAME, f"{cal_id}:{event['id']}")
            stats.deleted += 1
        else:
            _ingest(db, cal_id, event, stats)

    if new_token:
        sync_state.set_(SOURCE_NAME, scope=scope, ts=f"tok:{new_token}")
    else:
        sync_state.set_(SOURCE_NAME, scope=scope, ts=sync_state.now_iso())


# ---------- HTTP ----------

def _fetch_events(
    hdrs: dict, cal_id: str,
    sync_token: str | None, days_back: int, days_ahead: int,
) -> tuple[list[dict], str | None]:
    url = f"{CAL_BASE}/calendars/{cal_id}/events"

    if sync_token:
        params: dict = {
            "syncToken": sync_token,
            "showDeleted": "true",
            "maxResults": PAGE_SIZE,
        }
    else:
        now = datetime.now(tz=timezone.utc)
        params = {
            "timeMin": (now - timedelta(days=days_back)).isoformat(),
            "timeMax": (now + timedelta(days=days_ahead)).isoformat(),
            "singleEvents": "true",
            "orderBy": "updated",
            "maxResults": PAGE_SIZE,
        }

    events: list[dict] = []
    new_token: str | None = None

    while True:
        r = requests.get(url, headers=hdrs, params=params, timeout=30)
        if r.status_code == 410:
            raise _GoneError()
        if r.status_code == 404:
            print(f"[gcal] calendar not found or not accessible: {cal_id}")
            return [], None
        if r.status_code == 403:
            msg = r.json().get("error", {}).get("message", "")
            raise RuntimeError(
                f"[gcal] 403 on calendar '{cal_id}': {msg}\n"
                "Check that the Calendar API is enabled and ADC has "
                "the calendar.readonly scope."
            )
        r.raise_for_status()
        data = r.json()
        events.extend(data.get("items") or [])
        new_token = data.get("nextSyncToken")
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        params = {"pageToken": page_token}

    return events, new_token


# ---------- Event → Note ----------

def _ingest(db: Surreal, cal_id: str, event: dict, stats: SyncStats) -> None:
    event_id = event.get("id") or ""
    if not event_id:
        stats.skipped += 1
        return

    summary = event.get("summary") or "(no title)"
    description = event.get("description") or ""
    location = event.get("location") or ""
    start = _pick_dt(event.get("start") or {})
    end = _pick_dt(event.get("end") or {})
    modified_at = event.get("updated") or ""
    attendees = event.get("attendees") or []

    body = _build_body(description, location, start, end, attendees)
    path = f"{cal_id}:{event_id}"

    note_id = builder.upsert_note(
        db,
        source=SOURCE_NAME,
        path=path,
        title=summary,
        body=body,
        modified_at=modified_at,
    )

    # Cross-references in summary + description
    ref_text = f"{summary}\n{description}"
    builder.link_note_references(db, note_id, ref_text)

    # Attendee participation edges
    for att in attendees:
        name = att.get("displayName") or att.get("email") or ""
        if not name:
            continue
        person_id = builder.upsert_person(db, name)
        builder.relate_participation(db, person_id, note_id, role="attendee")

    stats.events += 1


def _pick_dt(dt_obj: dict) -> str:
    """Return dateTime or date from a Calendar API start/end object."""
    return dt_obj.get("dateTime") or dt_obj.get("date") or ""


def _build_body(
    description: str, location: str, start: str, end: str,
    attendees: list[dict],
) -> str:
    parts: list[str] = []
    if description:
        parts.append(description.strip())
    if location:
        parts.append(f"Location: {location}")
    if start:
        parts.append(f"Start: {start}")
    if end:
        parts.append(f"End: {end}")
    if attendees:
        names = []
        for a in attendees:
            name = a.get("displayName") or ""
            email = a.get("email") or ""
            if name and email:
                names.append(f"{name} ({email})")
            elif email:
                names.append(email)
            elif name:
                names.append(name)
        if names:
            parts.append("Attendees: " + ", ".join(names))
    return "\n".join(parts)
