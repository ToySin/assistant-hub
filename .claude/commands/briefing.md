# /briefing — Session-start workspace briefing

Reads the active workspace's dashboard and graph and produces a
structured summary of where things stand. Use at session start, after
`/monitor`, or whenever you need to re-orient.

## Prerequisites

- `ASSISTHUB_WORKSPACE` is set.
- The workspace's graph DB exists (run an ETL first if you haven't).

## Procedure

### Step 1. Collect data

```bash
python -m library.briefing
```

This prints:
- **Focus / blockers / action items** from `dashboard.yaml`
- **Open issues** grouped by source (jira / github / note)
- **Open PRs**
- **Blocked chains** from the graph (`blocked_by` edges)
- **Orphan issues** — open items with no PR, not blocking/blocked (from `graph_queries.dead_issues`)
- **Projects** — graph summary + `projects/*.yaml` tracker files
- **GitHub Notifications** — participating notifications via `gh api`
- **Today's schedule** — Google Calendar events (requires ADC + Calendar API)

Optional flags:
```bash
python -m library.briefing --no-gcal        # skip Calendar fetch
python -m library.briefing --no-gh-notifs   # skip GitHub Notifications
python -m library.briefing --no-timeline    # skip monitor replay section
python -m library.briefing --keep-cursor    # don't auto-advance replay cursor
```

### Step 2. Add prioritization

Read the output, then briefly call out:
- Top 1–3 priorities for this session (cite the issue keys)
- Anything blocked or stuck (cite the chain)
- Anything in the orphan list that should be promoted, closed, or assigned a PR
- Upcoming meetings from the calendar that need prep

Keep it short — the user reads this every session.

### Step 3. (Optional) Refresh first

If the data looks stale (e.g., an issue you just closed still shows as
open), refresh the graph before briefing:

```bash
python -m library.sources.run    # re-pull all enabled sources
```

## Google Calendar setup (optional)

Install the client library:
```bash
pip install google-api-python-client google-auth
```

Authenticate with ADC (one-time):
```bash
gcloud auth application-default login \
  --scopes=openid,https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/calendar.readonly
```

The Calendar API must be enabled on the GCP project. If it's disabled
or credentials are missing, the calendar section is silently skipped.

## Notes

- The python module is the data layer. This skill is the
  interpretation layer — keep your additions on top of the printed
  output, not inside it.
- For Jira/GitHub PRs to appear, the workspace's `sources.yaml` must
  enable them and `.env` must hold any required credentials.
- Orphan issues surface issues that have drifted out of active work.
  A large orphan list is a signal to prune the backlog.
