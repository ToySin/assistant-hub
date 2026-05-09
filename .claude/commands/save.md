# /save — Reflect session learnings into the workspace

End-of-session ritual: take what was learned this conversation and
persist it as static knowledge in the active workspace, so the next
session can pick up cold and not re-learn.

For mid-session snapshots use `/checkpoint` instead — it focuses on
dashboard / project state rather than knowledge accumulation.

## When to use proactively

Watch for moments that *should* generate persistent knowledge:
- Resolving an incident or unfamiliar problem ("ah it was X all along")
- Discovering a non-obvious config / mapping / workflow
- Establishing a new convention the user explicitly endorsed
- A hub or external doc was hard to find — surface a pointer

When you spot one, propose `/save` instead of letting the insight
evaporate at session end.

## Procedure

### Step 1. Locate the workspace's static surface

```bash
ls $(python -c 'from library.workspace import get_workspace_path; print(get_workspace_path())')/
```

Workspace static surface (ignore subdirs not present):
- `dashboard.yaml` — focus / blockers / action items / projects
- `knowledge/` — domain notes, mappings, command templates
- `runbooks/` — operational recipes; `runbooks/postmortems/` for incidents
- `projects/` — per-project trackers
- `CLAUDE.md` — workspace-level agent index, if present

Also relevant: `<workspace>/notes/` (free-form notes; this is also where
captured ideas live under `notes/ideas/`).

### Step 2. Sift the conversation

Pull out the *durable* learnings. Skip ephemeral context (current
debug state, stale errors). Categorize each candidate:

| Category | Target |
|----------|--------|
| Persistent fact / mapping / config value | `knowledge/<topic>.md` |
| Operational recipe (run X, check Y) | `runbooks/<name>.md` |
| Incident write-up | `runbooks/postmortems/YYYY-MM-DD-<slug>.md` |
| Concept worth remembering for the agent | `CLAUDE.md` (workspace-level) |

### Step 3. Propose, don't write blindly

For each candidate, show the user a short proposal:

> 다음을 `knowledge/redis-tuning.md`에 추가하려고 합니다 (요약 한 줄).
> 동의하시면 `y`, 다르게 하려면 코멘트.

Apply only after confirmation. Edit existing files in place (don't
shadow with new ones).

### Step 4. Self-sufficiency check

After applying, **re-read the changed file** and verify a fresh agent
session could act on it without reconstructing the conversation.
Common failure mode: writing references that only make sense with
session context ("the issue we discussed", "that error").

Re-read **every** file you touched, including ones already touched
mid-session — don't assume "already reflected" is good enough.

### Step 5. Postmortem nudge (incidents only)

If this session was incident investigation:
- Check `runbooks/postmortems/` for an existing entry on the same incident
- If none, propose creating one (date + 1-line slug). Skip if the user
  declines — postmortems are theirs to gate.

### Step 6. Tell the user what happened

One short summary of files added/changed. Stop.

## Notes

- Never write to `.env`. If a config you learned is actually a secret,
  point at `.env.example` and stop.
- Workspace data is private; don't echo full file contents to chat
  beyond what's needed to confirm the change.
- The active workspace's `dashboard.yaml` is updated by `/checkpoint`,
  not here. /save is for *static* knowledge, /checkpoint for *state*.
