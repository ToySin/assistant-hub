# /runbooks — Spec reference

Read once at the start of any /runbooks branch. Use as the source of
truth when discussing patterns, policies, or substitution variables.

## What a runbook is

A runbook is `(pattern → steps)`:

- **Pattern** decides which monitor events the runbook applies to.
- **Steps** describe what to do (rendered shell commands, in order).

Each execution records success / failure. The runbook walks up the
automation ladder (`manual → semi-auto → auto`) as evidence accumulates
and walks back down on failure.

## Lifecycle

```
  1st success on a manual runbook  → promote to semi-auto
  2nd success on semi-auto         → promote to auto (default policy)
  1 failure on auto                → demote to semi-auto
  semi-auto where fail ≥ success   → demote back to manual
```

Threshold values live in the `promotion_policies` table, so different
work contexts can tune aggressiveness independently.
`python -m library.runbooks policies` shows current values.

## Pattern fields

All but `--kind` optional:

| Flag | Matches against |
|------|-----------------|
| `--kind` | `event.kind` exact (e.g. `issue.closed`) |
| `--source` | `event.source` exact (e.g. `github_issues`, `jira`, `github`) |
| `--subject-pattern` | Python regex against `event.subject_key` |

## Step substitution

Available in `--command` strings, expanded at render time:

- `$subject_key`, `$source`, `$kind`, `$scope`
- `$payload_<key>` for any field in the event payload

`--command` may be repeated for multi-step resolutions; they render
in order.

## Dedup

Runbooks are keyed by `pattern_hash` (sha1 of the canonicalized
pattern). Trying to create a second runbook with the same pattern
errors out — edit the existing one or pick a different pattern.

## Storage caveats

- DB lives in `<workspace>/db/events.db` next to the monitor events
  (gitignored, regenerable in concept — but creating runbooks IS the
  work product, so back them up via `exports/` before nuking).
- Auto-execution is **not wired yet**. v1 only supports `match` +
  `render` so the agent / user can run the commands themselves and
  record the outcome. Auto-execute lands when `/act` learns to read
  the runbook table.
