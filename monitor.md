# /monitor — Event timeline + since-last-session replay

A workspace-local SQLite event store. Each ETL run diffs the prior
graph state of every fetched item against the new payload and emits
typed events: `issue.opened`, `issue.closed`, `issue.reopened`,
`issue.status_changed`, `issue.title_changed`. `/briefing` reads
events since the last `mark-replayed` to show "what changed while I
was gone".

## Procedure

### Show timeline

```bash
python -m library.monitor timeline           # latest 50
python -m library.monitor timeline --limit 5
python -m library.monitor timeline --since 2026-04-01
```

### Show only events since last replay

```bash
python -m library.monitor since-last-replay
```

This is what `/briefing` calls automatically — no need to invoke
manually unless you want raw output.

### Advance the replay cursor

```bash
python -m library.monitor mark-replayed
```

Run this once you've digested the events `/briefing` showed you. Next
briefing will only surface events newer than this moment.

### Index health

```bash
python -m library.monitor stats
```

Counts by event kind. Useful for a quick "is the collector firing?"
check.

## How the events are produced

Events are emitted **inline during ETL** by each source's
`_load_*()` function:

1. Look up the prior `(title, status)` of the item in the graph.
2. Upsert the item with the new payload.
3. Call `monitor.emit_issue_diff(...)` which compares old vs new and
   emits the right event kinds (or none if nothing changed).

This keeps the diff scoped to fields we care about and avoids
emitting noise on every single sync.

## Notes

- DB lives at `<workspace>/db/events.db` (gitignored, regenerable).
- The replay cursor is also workspace-local — it's per-laptop, so two
  laptops will each track their own "last seen".
- PRs aren't diffed yet (only Issues). Add when a workspace starts
  generating PR activity.
