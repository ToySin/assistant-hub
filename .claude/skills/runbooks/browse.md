# /runbooks — Branch: Browse existing runbooks

Show the user their runbook inventory. Filter / drill down as asked.

For pattern semantics and the lifecycle ladder, see
`.claude/skills/runbooks/_spec.md`.

## Commands

```bash
python -m library.runbooks list                  # all, grouped by automation level
python -m library.runbooks list --level auto     # only auto-promoted ones
python -m library.runbooks list --level semi-auto
python -m library.runbooks list --level manual
python -m library.runbooks view <id>             # full detail (pattern, steps, counters)
python -m library.runbooks policies              # promotion thresholds
```

## Suggested flow

1. Run `list` first to give the user the lay of the land.
2. If a specific runbook id catches their eye, follow up with `view <id>`.
3. If they ask "why is this still manual?" — pull `policies` and the
   counters from `view`, then explain against the ladder.
