# /runbooks — Self-reinforcing automation recipes

A runbook is `(pattern → steps)`. The pattern decides which monitor
events the runbook applies to; the steps describe what to do. Each
execution records success / failure, and the runbook walks up the
automation ladder (`manual → semi-auto → auto`) as evidence
accumulates and walks back down on failure. Threshold values live in
the `promotion_policies` table, so different work contexts can tune
aggressiveness independently.

## Lifecycle

```
  1st success on a manual runbook  → promote to semi-auto
  2nd success on semi-auto         → promote to auto (default policy)
  1 failure on auto                → demote to semi-auto
  semi-auto where fail ≥ success   → demote back to manual
```

## Procedure

### See what's already there

```bash
python -m library.runbooks list
python -m library.runbooks list --level auto
python -m library.runbooks view <id>
python -m library.runbooks policies
```

### Capture a manual resolution as a runbook

After resolving an event by hand, take the *exact* commands you ran
and turn them into a runbook so the next occurrence is faster:

```bash
python -m library.runbooks create \
    --name "log GH issue closes" \
    --kind issue.closed \
    --source github_issues \
    --command 'echo "[$(date)] $subject_key (was $payload_from)" >> /tmp/closed.log' \
    --from-event 42
```

Pattern fields (all but `--kind` optional):

| Flag | Matches against |
|------|-----------------|
| `--kind` | `event.kind` exact (e.g. `issue.closed`) |
| `--source` | `event.source` exact (e.g. `github_issues`, `jira`, `github`) |
| `--subject-pattern` | Python regex against `event.subject_key` |

Step substitution: `$subject_key`, `$source`, `$kind`, `$scope`,
plus `$payload_<key>` for any field in the event payload.

`--from-event` records the event id that motivated the runbook —
useful provenance.

`--command` may be repeated for multi-step resolutions; they render
in order.

### Find runbooks that fit a given event

```bash
python -m library.runbooks match <event-id>      # list candidates
python -m library.runbooks render <rb-id> <ev-id>  # show the rendered commands
```

`match` lists in priority order: `auto` first, then `semi-auto`,
then `manual`, ties broken by success count.

### Record an outcome

After running the rendered commands (manually or via auto-execution
when that lands), close the loop:

```bash
python -m library.runbooks record <id> success
python -m library.runbooks record <id> fail
```

Counts increment, automation level walks per the policy. Re-running
a known-bad runbook will demote it back to `manual` quickly so it
stops being suggested.

### Delete

```bash
python -m library.runbooks delete <id>
```

## Dedup

Runbooks are keyed by `pattern_hash` (sha1 of the canonicalized
pattern). Trying to create a second runbook with the same pattern
errors out — edit the existing one or pick a different pattern.

## Notes

- DB lives in `<workspace>/db/events.db` next to the monitor events
  (gitignored, regenerable in concept — but creating runbooks IS the
  work product, so back them up via `exports/` before nuking).
- Auto-execution is **not wired yet**. v1 only supports `match` +
  `render` so the agent / user can run the commands themselves and
  record the outcome. Auto-execute lands when `/act` learns to read
  the runbook table.
