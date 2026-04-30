# assistant-hub — Claude Agent Index

This file is the entry point for any agent working in this repo. It points
at where things live and which skill to invoke for which workflow.

For human-readable docs, see [README.md](./README.md).

## Active workspace

Most workflows assume `ASSISTHUB_WORKSPACE` is set (the workspace short
name). Workspaces live at `~/repositories/assisthub-ws-<name>/`.

## Skills

| Skill | Purpose | When to use |
|-------|---------|-------------|
| [`new-workspace.md`](./new-workspace.md) | Create a new workspace repo (local + private GitHub) | Bootstrap a new context (work / personal / per-project) |
| [`configure-sources.md`](./configure-sources.md) | Interactively fill the active workspace's `sources.yaml` | After `/new-workspace`, or to add/modify data sources later |
| [`briefing.md`](./briefing.md) | Session-start summary (open issues, PRs, blockers) | Begin of session, or when re-orienting mid-session |

## Code

| Path | Role |
|------|------|
| `library/workspace.py` | Resolve active workspace path / DB path / exports dir |
| `library/sources/config.py` | Load `sources.yaml`, resolve `auth_env` from `.env` |
| `library/sources/{jira,github,github_issues}.py` | Per-source ETL — pull + transform + load |
| `library/sources/run.py` | ETL orchestrator — `python -m library.sources.run` |
| `library/briefing.py` | Briefing data layer — `python -m library.briefing` |
| `library/enrichment.py` | L2 concept extraction via Claude — `python -m library.enrichment` (needs `ANTHROPIC_API_KEY`) |
| `graph/schema.surql` | SurrealDB schema (Issue is unified across sources) |
| `graph/builder.py` | Connection + UPSERT helpers + `relate()` |
| `graph/sync.py` | jsonl export/import (cross-laptop sync target) |
| `graph/link_extractor.py` | Regexes for Jira keys / PR refs in free text |

## Scripts

| Path | Role |
|------|------|
| `scripts/new-workspace.sh` | Workspace bootstrap (called by `/new-workspace`) |
| `scripts/install-hooks.sh` | Copy git hooks into a target repo |
| `scripts/hooks/{pre-commit,pre-push}` | Block secrets / `.env` from being committed or pushed |
| `scripts/sync-session.sh` | Snapshot Claude Code session jsonl into the workspace `sessions/` |
| `scripts/restore-session.sh` | On a fresh laptop, copy the workspace's session jsonl back so `claude --resume` works |

## Common workflows

```bash
# New workspace
./scripts/new-workspace.sh <name>            # then /configure-sources

# Refresh graph from configured sources
ASSISTHUB_WORKSPACE=<name> python -m library.sources.run

# Briefing
ASSISTHUB_WORKSPACE=<name> python -m library.briefing

# Cross-laptop session continuity
./scripts/sync-session.sh                    # before leaving laptop A
./scripts/restore-session.sh                 # after cloning on laptop B
```

## Conventions

- Workspace data is committed as **jsonl exports** under `<workspace>/exports/`,
  not as the binary SurrealKV directory.
- Secrets stay in `<workspace>/.env` — never in `sources.yaml`. The git
  hooks block accidental commits of `.env` files and known token shapes.
- New skills/scripts default to `assistant-hub` core unless they are
  workspace-specific.
