# /runbooks — Branch: Find runbooks for an event

Given an event id, show which runbooks apply and what their commands
would expand to. Used during `/act` and during ad-hoc resolution.

For pattern semantics, see `.claude/skills/runbooks/_spec.md`.

## Commands

```bash
python -m library.runbooks match <event-id>        # list candidates
python -m library.runbooks render <rb-id> <ev-id>  # show the rendered commands
```

`match` lists in priority order: `auto` first, then `semi-auto`,
then `manual`; ties broken by success count.

## Suggested flow

1. Call `match <event-id>`. If empty, tell the user no runbook
   applies and offer to create one (delegate to
   `.claude/skills/runbooks/create.md`).
2. If exactly one matches and it's `auto`-level, surface its rendered
   command and ask whether to run it.
3. If multiple match, show them ordered with their levels and
   counters. Let the user pick by id, then `render` it.
4. After running the rendered commands, hand off to
   `.claude/skills/runbooks/outcome.md` so the user can record
   success or failure (the lifecycle ladder needs it).
