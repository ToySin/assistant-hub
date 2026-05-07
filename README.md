# assistant-hub

A personal context platform for AI-assisted work automation. Pulls structured
data from your work tools (Jira, GitHub, Slack, Calendar, Drive, ...) into a
local knowledge graph so AI agents can brief you, prioritize work, and
automate recurring tasks with full cross-tool context.

## Why

Modern work spans many tools. Jira holds tickets, GitHub holds code, Slack
holds conversations, Calendar holds time, Drive/Notion holds docs. AI
assistants are most useful when given context — but no single assistant has
your private cross-tool view, and feeding everything ad-hoc into a chat is
slow and stateless.

assistant-hub keeps that context in a local SurrealDB graph **you own**.
Skills like `/briefing` and `/act` query the graph to produce a coherent
view of what's open and what to work on next, without leaking data to
third-party services.

## How it works

**One core repo, many workspace repos:**

- **`assistant-hub`** (this repo) — the public core: schema, ETL adapters,
  skills, scripts. Shared across all your workspaces. No personal data.
- **`assisthub-ws-<name>`** — a *workspace* repo. You create one per
  context (work, personal, per-project), and you can have as many as you
  want. Each holds that workspace's dashboard, knowledge files, graph
  exports, and Claude Code session snapshots. Always private.
  Bootstrapped by `scripts/new-workspace.sh`.

The active workspace is selected per shell via the `ASSISTHUB_WORKSPACE`
env var, or globally via a pointer file (`assisthub use <name>`). All
skills and ETL operations target whichever workspace is active.

**Two-layer graph:**

- **Layer 1 — structured ETL.** Typed nodes from APIs (`Issue`, `GitHubPR`,
  `Person`, `Project`) connected by typed edges (`assigned_to`, `implements`,
  `belongs_to`, `blocked_by`).
- **Layer 2 — LLM enrichment.** `Concept` nodes extracted from issue/PR
  text, linked via `mentions` edges carrying provenance, confidence, and
  the model that produced them.

Both layers live in the same embedded SurrealDB instance per workspace.

## Quickstart

Prereqs: `git`, `python3`, `gh` (authenticated), and optionally
[Claude Code](https://docs.claude.com/en/docs/claude-code) for the slash
commands.

### Option A — clone & use directly

```bash
gh repo clone <owner>/assistant-hub ~/repositories/assistant-hub
cd ~/repositories/assistant-hub

# 1. Create your first workspace (creates a private GitHub repo too)
./scripts/new-workspace.sh <workspace-name>
# (or, in Claude Code, just run /ws-config — it walks you through 1+3
#  conversationally and uses connected tools to discover IDs)

# 2. Bootstrap the laptop (hooks + venv + active workspace + session restore)
./scripts/setup.sh <workspace-name>

# 3. Configure sources
#    /ws-config in Claude (recommended — interactive, validates inputs,
#    surfaces tool-aided menus instead of asking for IDs from memory),
#    or edit <workspace>/sources.yaml by hand and add creds to <workspace>/.env

# 4. Run the ETL
python -m library.sources.run

# 5. Use it
python -m library.briefing
python -m library.act
python -m library.search "<query>"
```

### Option B — fresh-laptop one-liner

Once you have `assistant-hub` and at least one workspace repo on GitHub,
any new laptop can bootstrap with:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/<your-fork>/assistant-hub/main/scripts/setup.sh) <workspace-name>
```

This clones both repos, installs git hooks, sets up the venv, marks the
workspace as active, and restores Claude Code session files so you can
resume mid-conversation.

## Repo layout

| Path | Purpose |
|------|---------|
| `library/sources/` | Per-source ETL adapters (jira, github, github_issues, gdrive_gemini, …) |
| `library/{briefing,act,monitor,runbooks,search,enrichment}.py` | Skill data layers |
| `library/workspace.py` | Resolve active workspace path and DB path |
| `graph/schema.surql` | SurrealDB schema (idempotent) |
| `graph/builder.py` | Connection + UPSERT helpers + `relate()` |
| `graph/sync.py` | jsonl export/import (cross-laptop sync target) |
| `scripts/` | Bootstrap and operational scripts |
| `templates/workspace/` | Files copied into each new workspace |
| `*.md` (top level) | Claude Code slash command skills |

[`CLAUDE.md`](./CLAUDE.md) is the full index — start there if you'll be
working in this repo with an AI agent.

## Available skills

Run via `/<name>` in Claude Code, or by reading the corresponding markdown
file in another agent.

| Skill | What it does |
|-------|--------------|
| [`ws-config`](./ws-config.md) | Workspace lifecycle — create / switch / configure sources / status (single conversational entry) |
| [`briefing`](./briefing.md) | Session-start summary (open issues, PRs, blockers) |
| [`act`](./act.md) | Graph-driven priority queue — pick the next item |
| [`search`](./search.md) | Local FTS over Issue/PR bodies (SQLite FTS5 sidecar) |
| [`monitor`](./monitor.md) | Event timeline + replay cursor for /briefing |
| [`runbooks`](./runbooks.md) | Self-reinforcing recipes — recurring patterns become reusable steps |

## Conventions

- **Secrets stay in `<workspace>/.env`**, never in `sources.yaml`. The
  latter only holds pointers via `auth_env: VAR_NAME`. Pre-commit and
  pre-push hooks block accidental commits of `.env` files and known
  token shapes (GitHub, Anthropic, OpenAI, Slack, AWS, BEGIN PRIVATE
  KEY blocks).
- **Workspace data is committed as jsonl exports** under
  `<workspace>/exports/`, not as the binary SurrealKV directory.
  Diff-friendly and merge-friendly across laptops.
- **Cross-laptop continuity** via `sync-session.sh` / `restore-session.sh`,
  which snapshot Claude Code session jsonl files into the workspace repo
  so `claude --resume <id>` works on any laptop.
- **Workspace = sync target.** Most workspace files are produced by
  skills running in that workspace context; manual edits are rare.
- **Default placement.** New features land in `assistant-hub` core
  unless they are workspace-specific.

## Data sources currently implemented

Out of the box: `jira`, `github`, `github_issues`, `gdrive_gemini`. Many
more are scaffolded in `templates/workspace/sources.yaml` (linear, slack,
gmail, confluence, notion, gcal, obsidian, rss, …) — adding an adapter is
a self-contained module under `library/sources/`.

## Status

Personal project, in active development. APIs and patterns may still
shift. Forks welcome — please do not file issues for missing source
adapters; add them and open a PR if you'd like them upstream.

## License

TBD.
