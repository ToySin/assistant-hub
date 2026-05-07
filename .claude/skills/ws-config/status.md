# /ws-config — Branch 4: Workspace status check

Always-applicable rules: see `.claude/skills/ws-config/_rules.md`.

Render a single tidy status block covering: which sources are enabled,
which env vars they need vs which are set, last sync per source,
export row counts, and a one-line recommendation.

## 1. Active workspace

```bash
~/repositories/assistant-hub/scripts/assisthub current
```

## 2. Enabled sources

Parse `<workspace>/sources.yaml`, list the names where `enabled: true`.

## 3. Env-var coverage

For each enabled source's `auth_env`, mark ✓ if set in the
workspace's `.env`, ✗ if missing.

## 4. Last sync per source

Read `<workspace>/sync_state.json` (it's per-machine and gitignored —
absent on a freshly cloned workspace). Render as
`<source>: <iso-timestamp>` or "(never)".

## 5. Exports state

For each `<workspace>/exports/graph/*.jsonl`, count rows. List the
non-empty ones.

## 6. Render

> ## `<name>` 상태
>
> **활성 소스 (4)**: `github`, `github_issues`, `markdown_dirs`, `jira`
>
> **환경변수**:
>   ✓ GITHUB_TOKEN, JIRA_EMAIL, JIRA_TOKEN
>   ✗ (없음)
>
> **마지막 동기화**:
>   - github         2026-05-06T14:22:11Z
>   - github_issues  2026-05-06T14:22:13Z
>   - jira           (한 번도 안 돌림)
>   - markdown_dirs  2026-05-07T09:01:55Z
>
> **Export rows**: Issue 14, Note 8, Concept 12, mentions 31
>
> **추천**: jira 첫 ETL 실행 — `python -m library.sources.run --source jira`

## 7. Recommendation rules

- Any enabled source with a missing env var → tell the user which env
  vars to add.
- Any enabled source with `last sync = (never)` → suggest the first
  ETL command for that source.
- Any source synced >24h ago and the user is starting a session →
  suggest a refresh.
- Otherwise: "looks healthy".
