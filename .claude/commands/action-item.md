# /action-item — Manage `action_items` in the workspace dashboard

Tiny CRUD over `<workspace>/dashboard.yaml` `action_items[]`.

## Args

| Arg | Behavior |
|-----|----------|
| (none) | List current action items, grouped pending vs done |
| `done <N>` | Mark item N (1-indexed in the pending list) as `done: true` |
| `rm <N>` | Remove item N entirely |
| (other text) | Add as a new pending action item |

## Procedure

### Step 1. Resolve target file

```bash
DASH=$(python -c 'from library.workspace import get_workspace_path; print(get_workspace_path() / "dashboard.yaml")')
```

Read it. The `action_items` field is a list of objects:

```yaml
action_items:
  - text: "ping reviewer on PR #123"
    done: false
    added: 2026-05-09
  - text: "rotate Jira PAT"
    done: true
    added: 2026-05-08
    completed: 2026-05-09
```

If `action_items` is missing or null, treat as empty list.

### Step 2. Dispatch on args

#### `(none)` — list

Render two sections:

```
## Pending (3)
1. ping reviewer on PR #123  (added 2026-05-09)
2. rotate Jira PAT           (added 2026-05-08)
3. write postmortem          (added 2026-05-08)

## Done (recent)
- ✅ <text>  (completed 2026-05-09)
```

Show last 5 done items only.

#### `done <N>` — mark complete

Resolve N against the *pending* list (1-indexed). Set `done: true` and
add `completed: <today>`. Use Edit tool — minimal change, preserve
ordering and any other fields.

If N is out of range, show the list and ask again.

#### `rm <N>` — remove

Resolve N against pending. Confirm once ("정말 제거할까요?"), then
remove the entry.

#### (text) — add

Append a new entry:

```yaml
- text: "<text verbatim>"
  done: false
  added: <today YYYY-MM-DD>
```

If duplicate text already exists in pending, ask whether to add anyway
or update the existing one's date.

### Step 3. Confirm

One short summary of what changed.

## Notes

- Use the Edit tool for minimal in-place YAML edits. Don't reformat
  the whole file.
- `dashboard.yaml`'s other fields (`focus`, `blockers`, `projects`)
  are managed by `/checkpoint`, not here.
- For longer-lived TODOs (effort estimate, related issues), use
  `/idea capture` instead — action items are *this week* scope.
