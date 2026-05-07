# assistant-hub — Claude Agent Index

This file is the entry point for any agent working in this repo. It points
at where things live and which skill to invoke for which workflow.

For human-readable docs, see [README.md](./README.md).

## Active workspace

Workspaces live at `~/repositories/assisthub-ws-<name>/`. Active workspace
is resolved as: `ASSISTHUB_WORKSPACE` env var first (per-shell override),
then the pointer file at `~/.config/assisthub/active`.

```bash
assisthub use <name>     # set the pointer
assisthub current        # show active
assisthub list           # list workspaces (* marks active)
```

(Symlink `scripts/assisthub` onto your PATH once.)

## Skills

All skills live in `.claude/commands/<name>.md`. Claude Code picks them
up automatically when the cwd is this repo or a workspace (workspaces
get symlinks at create time — see `scripts/new-workspace.sh`).

| Skill | Purpose | When to use |
|-------|---------|-------------|
| [`ws-config`](./.claude/commands/ws-config.md) | Workspace lifecycle — create / switch / configure sources / status | Setting up a new context, adding data sources, or checking workspace health |
| [`briefing`](./.claude/commands/briefing.md) | Session-start summary (open issues, PRs, blockers) | Begin of session, or when re-orienting mid-session |
| [`act`](./.claude/commands/act.md) | Assess + prioritize → pick the next item | After `/briefing`, when deciding what to work on |
| [`search`](./.claude/commands/search.md) | Local FTS over Issue / PR bodies | Find a ticket by phrase, look up prior context |
| [`monitor`](./.claude/commands/monitor.md) | Event timeline (open/close/title/status) + replay cursor | After `/briefing`, or to inspect what changed |
| [`runbooks`](./.claude/commands/runbooks.md) | Self-reinforcing recipes — pattern → steps with promote/demote | After resolving a recurring event by hand |

## Code

| Path | Role |
|------|------|
| `library/workspace.py` | Resolve active workspace path / DB path / exports dir |
| `library/sources/config.py` | Load `sources.yaml`, resolve `auth_env` from `.env` |
| `library/sources/{jira,github,github_issues,gdrive_gemini,markdown_dirs,notion,confluence}.py` | Per-source ETL — pull + transform + load |
| `library/sources/run.py` | ETL orchestrator — `python -m library.sources.run` |
| `library/briefing.py` | Briefing data layer — `python -m library.briefing` |
| `library/act.py` | Act data layer (P0–P3 ranking) — `python -m library.act` |
| `library/search.py` | SQLite FTS5 sidecar — `python -m library.search "<query>"` |
| `library/monitor.py` | Event store (timeline + replay cursor) — `python -m library.monitor timeline` |
| `library/runbooks.py` | Runbook store + lifecycle — `python -m library.runbooks list` |
| `library/sync_state.py` | Per-(source, scope) last-sync timestamps backing delta ETL |
| `library/enrichment.py` | L2 concepts + action items extraction — `python -m library.enrichment` |
| `library/llm.py` | Provider-agnostic LLM client (Anthropic default; switch to local Ollama / OpenAI-compatible via env) |
| `graph/schema.surql` | SurrealDB schema (Issue is unified across sources) |
| `graph/builder.py` | Connection + UPSERT helpers + `relate()` |
| `graph/sync.py` | jsonl export/import (cross-laptop sync target) |
| `graph/link_extractor.py` | Regexes for Jira keys / PR refs in free text |

## Scripts

| Path | Role |
|------|------|
| `scripts/setup.sh` | Bootstrap a fresh laptop (clone + hooks + venv + session restore) |
| `scripts/assisthub` | Active-workspace switcher CLI (use / current / list / unset) |
| `scripts/new-workspace.sh` | Workspace bootstrap mechanics (git init, gh repo create, hooks). Invoked by `/ws-config`. |
| `scripts/install-hooks.sh` | Copy git hooks into a target repo |
| `scripts/hooks/{pre-commit,pre-push}` | Block secrets / `.env` from being committed or pushed |
| `scripts/sync-session.sh` | Snapshot Claude Code session jsonl into the workspace `sessions/` |
| `scripts/restore-session.sh` | On a fresh laptop, copy the workspace's session jsonl back so `claude --resume` works |

## Common workflows

```bash
# Fresh-laptop bootstrap (clone + hooks + venv + session restore)
./scripts/setup.sh <workspace>

# New workspace
./scripts/new-workspace.sh <name>            # raw script; or use /ws-config for the full conversational flow

# Refresh graph from configured sources
python -m library.sources.run                # delta sync (uses sync_state)
python -m library.sources.run --full         # ignore sync_state, re-fetch all

# Briefing + Act
python -m library.briefing
python -m library.act

# Cross-laptop session continuity
./scripts/sync-session.sh                    # before leaving laptop A
./scripts/restore-session.sh                 # after cloning on laptop B (setup.sh runs this)
```

## Conventions

- Workspace data is committed as **jsonl exports** under `<workspace>/exports/`,
  not as the binary SurrealKV directory.
- Secrets stay in `<workspace>/.env` — never in `sources.yaml`. The git
  hooks block accidental commits of `.env` files and known token shapes.
- New skills/scripts default to `assistant-hub` core unless they are
  workspace-specific.
- L2 enrichment uses whatever LLM `library/llm.py` resolves. Default is
  Anthropic + `ANTHROPIC_API_KEY`. To switch to a local Ollama box or
  any OpenAI-compatible endpoint, set:

  ```
  ASSISTHUB_ENRICHMENT_PROVIDER=openai_compatible
  ASSISTHUB_ENRICHMENT_MODEL=llama3.1:70b
  ASSISTHUB_ENRICHMENT_BASE_URL=http://<host>:11434/v1
  ```

  The provider/model label is recorded in `extracted_by` on every
  enrichment edge for provenance.
