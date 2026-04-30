# /configure-sources — Interactively fill an assistant-hub workspace's `sources.yaml`

Walks the user through enabling and configuring data sources for the active
workspace. Re-runnable: safe to invoke any time to add or modify sources
after initial workspace creation.

## Prerequisites

- `ASSISTHUB_WORKSPACE` is set (the active workspace's short name).
- The workspace exists at `~/repositories/assisthub-ws-$ASSISTHUB_WORKSPACE/`.
- Workspace `sources.yaml` exists (created by `/new-workspace`).

## Procedure

The configuration is a conversation, not a fill-in form. Walk through it
step by step. Use connected tools (MCP servers, `gh`, `glab`, etc.) for
discovery so the user does not need to remember IDs from memory.

### Step 1. Read current state

```bash
cat ~/repositories/assisthub-ws-$ASSISTHUB_WORKSPACE/sources.yaml
```

Report which sources are currently enabled and which are not.

### Step 2. Pick categories to (re)visit

Ask the user which categories they want to configure now:

- Issue & task tracking — jira, linear, github_issues
- Code & PRs — github, gitlab, local_repos
- Communication — slack, gmail
- Docs & wikis — confluence, notion, gdrive_docs
- Calendar — gcal
- Notes & reading — obsidian, markdown_dirs, readwise
- Web feeds — rss
- Custom HTTP — http

The user may pick any subset; skip everything else.

### Step 3. For each chosen source, gather required fields

Use this discovery table. If a tool is connected, prefer it over asking the
user to type IDs from memory.

| Source | Required fields | Discovery helper (use if available) |
|--------|-----------------|-------------------------------------|
| jira | `base_url`, `project_keys` | Atlassian MCP `getAccessibleAtlassianResources` then `getVisibleJiraProjects` |
| linear | `team_keys` | Linear API; otherwise ask |
| github_issues, github | `repos` | `gh repo list <owner> --limit 50 --json nameWithOwner` |
| gitlab | `base_url`, `projects` | Ask user |
| slack | `channels` | Slack MCP `slack_search_channels` |
| gmail | `query` | Suggest examples (`from:boss newer_than:7d`); ask |
| confluence | `base_url`, `spaces` | Atlassian MCP `getConfluenceSpaces` |
| notion | `database_ids` and/or `page_ids` | Ask user |
| gdrive_docs | `folder_ids` | Drive MCP if connected; otherwise ask |
| gcal | `calendar_ids`, `days_back`, `days_ahead` | Calendar MCP if connected; defaults `["primary"]`, 7, 14 |
| obsidian | `vault_path` | Ask, then verify the directory exists |
| markdown_dirs | `paths` | Ask, then verify each directory exists |
| readwise | (none) | Just enable |
| rss | `feeds` | Ask for URL list |
| http | `endpoints` (list of `{name, url, auth_env, parser}`) | Ask per endpoint |

For each chosen source: ask only the required fields, validate where
possible, and remember the answers.

### Step 4. Identify required env vars

Aggregate every `auth_env` referenced by the newly enabled sources. Read
the workspace's `.env` (if it exists) and report which variables are
already set vs missing. Show the user exactly which lines they need to add
to `.env`.

### Step 5. Write `sources.yaml`

Edit `~/repositories/assisthub-ws-$ASSISTHUB_WORKSPACE/sources.yaml`:

- For each source the user enabled, set `enabled: true` and fill the
  fields gathered in Step 3.
- Leave untouched sources alone (do not blank out their existing config).
- Preserve the file's category comments and overall structure.

### Step 6. Confirm

Show the diff of `sources.yaml`. Print the env-var checklist from Step 4.
Tell the user the next step is to run the workspace's ETL (once it
exists) to populate the graph.

## Notes

- This skill never writes to `.env` directly — credentials stay in the
  user's hands.
- The skill only edits `sources.yaml`. It does not run ETL or touch the
  graph DB.
- Re-running this skill is safe: it merges with existing config rather
  than overwriting unrelated entries.
