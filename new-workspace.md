# /new-workspace — Create a new assistant-hub workspace

Bootstrap a new workspace repo (`assisthub-ws-<name>`) — local clone + private
GitHub repo, scaffolded from `templates/workspace/`.

## Args

| Arg | Behavior |
|-----|----------|
| `<name>` | Workspace short name. lowercase letters, digits, dashes. e.g., `work`, `personal`, `my-finance` |
| `--no-push` | Skip GitHub repo creation, local only |
| `--owner <gh-owner>` | Override GitHub owner (default: current `gh` user) |
| `--location <dir>` | Override base directory (default: `~/repositories`) |

## Steps

### Step 1. Validate inputs

- Confirm workspace `<name>` follows `^[a-z0-9][a-z0-9-]*$`.
- Confirm `~/repositories/assisthub-ws-<name>` does not already exist.
- Confirm `gh` is authenticated (unless `--no-push`).

### Step 2. Run the bootstrap script

```bash
./scripts/new-workspace.sh <name>
```

The script:
1. Copies `templates/workspace/` → `~/repositories/assisthub-ws-<name>/`
2. Substitutes `{{WORKSPACE_NAME}}` → `<name>` in template text files
3. `git init` + initial commit
4. `gh repo create <owner>/assisthub-ws-<name> --private` and push

### Step 3. Post-create configuration

Walk the user through:
1. `cp .env.example .env` and fill credentials (Jira, Google, etc. as relevant)
2. Edit `sources.yaml` — uncomment and configure data sources for this workspace
3. (Optional) Add the first project tracker in `projects/`

### Step 4. Confirm

Print:
- Local path
- GitHub URL
- Next-step checklist

## Notes

- Workspace repo is **private by default**. It serves as a sync target for
  workspace data (dashboard, knowledge, DB exports). Manual edits are uncommon.
- DB files (Neo4j, SQLite) are **not** committed as binaries — they sync via
  `exports/` directory containing Cypher dumps / SQL dumps. (Sync skill: TBD.)
- To switch active workspace later: `export ASSISTHUB_WORKSPACE=<name>`
  (workspace switcher skill: TBD).
