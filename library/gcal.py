"""Google Calendar — live fetch of today/tomorrow events for briefing.

Data is NOT stored in the graph (events are too ephemeral for ETL).
Called once per briefing session and discarded.

Auth: Application Default Credentials (ADC). One-time setup:
  gcloud auth application-default login \
    --scopes=openid,\
https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/calendar.readonly

Requires google-api-python-client + google-auth to be installed:
  pip install google-api-python-client google-auth

If credentials are missing, the API is disabled, or the package is not
installed, returns [] and prints a one-line warning so briefing still
completes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def today_events(days_ahead: int = 1) -> list[dict]:
    """Return events for today + `days_ahead` days from the primary calendar.

    Each item: {summary, start, end, location}. Times are ISO-8601 strings.
    Returns [] gracefully on any failure.
    """
    try:
        import google.auth
        from googleapiclient.discovery import build  # type: ignore[import]
    except ImportError:
        return []

    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/calendar.readonly"]
        )
    except Exception:
        return []

    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now = datetime.now(tz=timezone.utc)
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=days_ahead + 1)
        data = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = []
        for e in data.get("items", []):
            start = e.get("start", {})
            end = e.get("end", {})
            events.append({
                "summary": e.get("summary") or "(no title)",
                "start": start.get("dateTime") or start.get("date", ""),
                "end": end.get("dateTime") or end.get("date", ""),
                "location": e.get("location") or "",
            })
        return events
    except Exception as exc:
        print(f"[gcal] warning: {exc}")
        return []
