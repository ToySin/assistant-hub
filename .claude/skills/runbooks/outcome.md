# /runbooks — Branch: Record outcome / delete

Close the loop after running a rendered runbook, or remove a runbook
that's no longer useful. The lifecycle ladder only moves when
outcomes are recorded — silent successes leave a runbook stuck at
`manual` forever.

For lifecycle thresholds, see `.claude/skills/runbooks/_spec.md`.

## Record outcome

```bash
python -m library.runbooks record <id> success
python -m library.runbooks record <id> fail
```

Counts increment, automation level walks per the policy. Re-running
a known-bad runbook will demote it back to `manual` quickly so it
stops being suggested.

If the user is unsure whether to record success or fail (partial
fix, manual touch-ups required, etc.), default to **fail** — the
ladder is conservative and re-promotion is cheap.

## Delete

```bash
python -m library.runbooks delete <id>
```

Confirm before running — there is no undo. Suggest the user keep an
`exports/` snapshot if the runbook represented real triage work.
