# /runbooks — Branch: Capture a manual resolution as a runbook

After resolving an event by hand, take the *exact* commands that
worked and turn them into a runbook so the next occurrence is faster.

For pattern fields, substitution variables, and dedup rules, read
`.claude/skills/runbooks/_spec.md` first.

## Conversation

1. Ask which event motivated this: get its id (or "skip" if there
   isn't one — `--from-event` is optional but recommended).
2. Ask for a short name (free text, e.g. `"log GH issue closes"`).
3. Inspect the event to suggest pattern fields:
   - `--kind` is required; default to the event's kind.
   - Offer `--source` if the user wants to scope to one source.
   - Offer `--subject-pattern` if the subject_key has structure worth
     matching (regex).
4. Collect the actual command(s) that resolved it. One command per
   `--command` flag; repeat for multi-step resolutions.
5. Show the full `python -m library.runbooks create ...` invocation
   for confirmation, then run it.

## Example invocation

```bash
python -m library.runbooks create \
    --name "log GH issue closes" \
    --kind issue.closed \
    --source github_issues \
    --command 'echo "[$(date)] $subject_key (was $payload_from)" >> /tmp/closed.log' \
    --from-event 42
```

## On dedup error

If create fails because `pattern_hash` already exists, surface the
existing runbook (`view <id>`) and ask whether to refine the pattern
(narrower regex, additional `--source`) or update the existing one.
Don't keep retrying with the same pattern.
