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
- Focus / blockers / action items from `dashboard.yaml`
- Open issues grouped by source (jira / github)
- Open PRs
- Blocked-by chains in the graph

### Step 2. Add prioritization

Read the output, then briefly call out:
- Top 1–3 priorities for this session (cite the issue keys)
- Anything blocked or stuck (cite the chain)
- Anything missing from the dashboard that should be promoted to focus

Keep it short — the user reads this every session.

### Step 3. (Optional) Refresh first

If the data looks stale (e.g. an issue you just closed still shows as
open), refresh the graph before briefing:

```bash
python -m library.sources.run    # re-pull all enabled sources
```

## Notes

- The python module is the data layer. This skill is the
  interpretation layer — keep your additions on top of the printed
  output, not inside it.
- For Jira/GitHub PRs to appear, the workspace's `sources.yaml` must
  enable them and `.env` must hold any required credentials.
