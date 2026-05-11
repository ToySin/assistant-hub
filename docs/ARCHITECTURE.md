# Architecture

## Two-repo design

```
assistant-hub/            ← public core (this repo)
assisthub-ws-<name>/      ← private workspace (one per context)
```

The core repo contains all code, skills, scripts, and schema. It has no
personal data. Workspace repos hold credentials, data exports, knowledge
files, and Claude Code session snapshots. You can have as many workspaces
as you need (work, personal, per-project).

Workspaces are created with `scripts/new-workspace.sh <name>`. The active
workspace is resolved at runtime: `ASSISTHUB_WORKSPACE` env var → pointer
file at `~/.config/assisthub/active` (set via `scripts/assisthub use <name>`).

## ETL → Graph → Skills flow

```
External APIs                SurrealDB graph           Slash commands
──────────────               ────────────────          ──────────────
Jira  ─────┐                 Issue nodes               /briefing
GitHub ────┤── L1 ETL ──→   GitHubPR nodes   ──→      /act
Notion ────┤                 Person nodes              /monitor
Drive ─────┤                 Note nodes                /search
Markdown ──┘                 Concept nodes             /runbooks
                               ↑
                             L2 enrichment (LLM)
```

**L1 (structured ETL)** runs via `python -m library.sources.run`. Each
adapter (`library/sources/<source>.py`) pulls from one external API,
transforms to typed nodes, and upserts into SurrealDB using
`graph/builder.py`. Delta-aware by default via `library/sync_state.py`.

**L2 (LLM enrichment)** runs via `python -m library.enrichment`. Reads
`Note` and `Issue` bodies and extracts: (a) `Concept` nodes linked via
`mentions`, (b) action-item `Issue` stubs linked via `extracted_from`,
(c) `Person` nodes linked via `mentions_person`. The model that extracted
each node is recorded in `extracted_by` for provenance.

## Workspace file layout

```
assisthub-ws-<name>/
  sources.yaml        ← which adapters to run + per-source config
  .env                ← secrets (never committed; git hooks block it)
  dashboard.yaml      ← action items, priorities, status
  knowledge/          ← static reference docs (git-settings, runbooks, ...)
  notes/              ← raw note files (markdown_dirs source can ingest these)
  projects/           ← per-project context files
  runbooks/           ← self-reinforcing incident recipes
  exports/            ← jsonl graph snapshots (committed, diff-friendly)
  sessions/           ← Claude Code session jsonl snapshots
  db/                 ← SurrealKV binary (git-ignored; rebuilt from exports)
  infrastructure.md   ← workspace-specific infra notes
```

Secrets live in `.env`. `sources.yaml` references them by env-var name
via `auth_env: VAR_NAME`. This keeps the workspace repo safe to commit.

## Slash commands + skills

`.claude/commands/<name>.md` files in the core repo define all skills.
Each workspace repo gets relative symlinks at create time so
`/<name>` works regardless of which directory is the cwd.

Complex skills follow a thin-router pattern:
```
.claude/commands/<name>.md       ← router (~50 lines): reads args, loads sub-skill
.claude/skills/<name>/           ← sub-skill files, one per mode
```

To add a new skill: create the `.md` in `assistant-hub/.claude/commands/`;
it will be picked up by all workspaces at next `link-commands.sh` run.
Workspace-specific skills go in `assisthub-ws-<name>/.claude/commands/`.

## Graph schema conventions

Defined in `graph/schema.surql` (applied idempotently).

- **Node tables**: `Issue`, `GitHubPR`, `Person`, `Project`, `Note`, `Concept`
- **Edge tables**: `assigned_to`, `implements`, `belongs_to`, `blocked_by`,
  `extracted_from`, `mentions`, `mentions_person`, `references_issue`, `references_pr`
- All node IDs are stable slugs of their natural key (source + external_key).
  Re-running ETL is always safe — upserts never duplicate.
- `status_category` on `Issue` uses Atlassian's universal vocabulary
  (`new / indeterminate / done / undefined`) so `/briefing` + `/act` work
  across locales and across source types (jira, note-extracted, linear, …).

## Cross-laptop continuity

`scripts/sync-session.sh` copies the active Claude Code session `.jsonl`
into `<workspace>/sessions/` and commits it. On a new laptop, `setup.sh`
(or `restore-session.sh`) copies the latest session back so
`claude --resume <id>` works without losing context.

Graph state is exported as jsonl under `exports/` before each laptop
switch and imported with `graph/sync.py` on the new machine.

## Adding a new ETL source

1. Create `library/sources/<name>.py` with a `sync(db, settings, auth) -> SyncStats` entry point.
2. Add a stanza to `templates/workspace/sources.yaml` (commented out by default).
3. Register the source name in `library/sources/run.py`.
4. If the source produces notes, call `builder.link_note_references(db, note_id, body)` after `builder.upsert_note(...)`.
