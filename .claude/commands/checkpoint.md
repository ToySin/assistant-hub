# /checkpoint — Mid-session snapshot of dashboard + projects

Capture working state without ending the session: update `dashboard.yaml`
and any active project trackers so context survives a context-window
compact, an interruption, or a laptop switch.

For end-of-session knowledge persistence use `/save` instead — it
targets static files (`knowledge/`, `runbooks/`), this targets *state*.

## Procedure

### Step 1. Update dashboard.yaml

```bash
DASH=$(python -c 'from library.workspace import get_workspace_path; print(get_workspace_path() / "dashboard.yaml")')
```

Read it, then reflect the conversation:

- `focus`: re-prioritize today's items, drop completed ones
- `blockers`: drop resolved, add new
- `action_items`: mark completed `done: true`, add new ones discovered
  this session
- `projects`: update summary / status if a project was touched

Use the Edit tool to make minimal in-place changes. Preserve
ordering and comments.

### Step 2. Update active project trackers

If `dashboard.yaml.projects` lists active project files, walk each:

```bash
ls $(python -c 'from library.workspace import get_workspace_path; print(get_workspace_path() / "projects")')/
```

For each project worked on this session:

- `tasks[].status`: advance the state machine where appropriate
  (`backlog → in_progress → in_review → done`)
- `tasks[].notes`: add implementation context, decisions, gotchas — what
  the *next* session needs to resume
- `tasks[].next_steps`: refresh the bullet list

### Step 3. Refresh the graph (cheap, optional)

If sources were touched this session (issues opened/closed, notes
written), refresh exports so cross-laptop sync is current:

```bash
python -m library.sources.run    # delta sync
```

Skip if nothing graph-relevant changed.

### Step 4. Tell the user what changed

One short summary: which dashboard fields, which project files.

## Notes

- `/checkpoint` is idempotent — running it twice in a row should be a
  no-op the second time.
- Don't move tasks to `done` without explicit user signal. "We talked
  about X" ≠ "X is done."
- Auto-sync hook commits `exports/` separately on session Stop;
  `/checkpoint` doesn't push.
