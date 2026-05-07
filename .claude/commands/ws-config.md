# /ws-config — Workspace lifecycle (create / switch / configure)

Single conversational entry point for everything workspace-related.
Branch at start based on what the user wants. **This is a
conversation — show menus, wait for answers, validate inputs, only
write/run things after explicit confirmation.**

Re-runnable. Korean is fine; match the user's language.

## Open

First, gather state to render an accurate menu:

```bash
~/repositories/assistant-hub/scripts/assisthub list 2>/dev/null   # workspaces (* marks active)
~/repositories/assistant-hub/scripts/assisthub current 2>/dev/null  # active name (or empty)
```

Then show:

> 현재 상태:
> - 활성 워크스페이스: `<name>`  (없으면 "(없음)")
> - 존재하는 워크스페이스: `hub-improvement`, `personal`, ...
>
> 뭐 하시겠어요?
>
> 1. 새 워크스페이스 만들기
> 2. 활성 전환
> 3. 활성 워크스페이스의 데이터 소스 설정
> 4. 활성 워크스페이스 상태 점검 (sources / env / exports)
> 5. 취소

Wait for the choice. Branch accordingly. After a branch finishes, ask
if they want to do anything else and either loop back to the menu or
say goodbye.

---

## Branch 1 — Create new workspace

### 1.1 Gather inputs

> 워크스페이스 이름 (소문자/숫자/대시, 알파넘으로 시작):

Validate against `^[a-z0-9][a-z0-9-]*$`. If invalid, restate the rule
and ask again. If `~/repositories/assisthub-ws-<name>/` already exists,
say so and bail back to the main menu.

> GitHub에 private 레포로 푸시할까요? (y/n, 기본 y)
> [if y] GitHub owner는 `<현재 gh user>` 그대로 갈까요? (y/n)

### 1.2 Run the bootstrap script

```bash
~/repositories/assistant-hub/scripts/new-workspace.sh <name>           # default = push
~/repositories/assistant-hub/scripts/new-workspace.sh <name> --no-push # local only
~/repositories/assistant-hub/scripts/new-workspace.sh <name> --owner <gh-owner>
```

The script handles: directory copy from `templates/workspace/`,
`{{WORKSPACE_NAME}}` substitution, `git init`, hook install, initial
commit, and (if pushing) `gh repo create --private --push`.

Report back:
- Local path
- GitHub URL (if pushed)

### 1.3 Set as active

> 방금 만든 `<name>`을 활성으로 설정할까요? (y/n)

If yes:

```bash
~/repositories/assistant-hub/scripts/assisthub use <name>
```

### 1.4 Roll into source configuration

> 새 워크스페이스에 데이터 소스도 지금 설정할까요? (y/n)

If yes, jump to Branch 3 with this workspace as the target.
If no, stop and remind them they can run `/ws-config` again later.

---

## Branch 2 — Switch active workspace

```bash
~/repositories/assistant-hub/scripts/assisthub list
```

Render as a numbered list with the asterisk on the current active.
Wait for choice (number or name).

```bash
~/repositories/assistant-hub/scripts/assisthub use <name>
```

Confirm the new active is what they expected.

---

## Branch 3 — Configure data sources for the active workspace

### 3.1 Read current state

```bash
cat ~/repositories/assisthub-ws-$(~/repositories/assistant-hub/scripts/assisthub current)/sources.yaml
```

Report which sources are `enabled: true`, which are `enabled: false`.

> 워크스페이스 `<name>`의 sources.yaml 상태:
>
> ✓ 활성화: `github`, `github_issues`
> ○ 비활성: `jira`, `linear`, `slack`, `markdown_dirs`, ...
>
> 어느 카테고리 손볼까요? 활성화한 것도 다시 손봐도 됩니다.

### 3.2 Pick categories

> 카테고리:
> 1. **Issue / task tracking** — `jira`, `linear`, `github_issues`
> 2. **Code & PRs** — `github`, `gitlab`, `local_repos`
> 3. **Communication** — `slack`, `gmail`
> 4. **Docs & wikis** — `confluence`, `notion`, `gdrive_docs`, `gdrive_gemini`
> 5. **Calendar** — `gcal`
> 6. **Notes** — `obsidian`, `markdown_dirs`, `readwise`
> 7. **Web feeds** — `rss`
> 8. **Custom HTTP** — `http`
>
> 번호나 이름으로 골라주세요 (다중 선택 OK):

Confirm what was chosen before moving on.

### 3.3 For each chosen source, gather fields one at a time

**Ask one thing at a time, validate, then move on.** Don't dump a form
of 5 questions; conversation > batch.

For every source, the loop is the same:

1. Tell the user which fields you need.
2. If a discovery tool is connected (Atlassian MCP, `gh`, Slack MCP,
   Drive MCP, ...), use it and present the results as a menu the user
   can pick from. Do not make them type IDs from memory.
3. Validate each answer (URL reachability, path exists, etc.) and ask
   again on failure with the specific error.
4. Note the answers in working memory; do NOT touch the file yet.

Per-source field map and discovery hints:

| Source | Required fields | Discovery helper |
|--------|-----------------|------------------|
| `jira` | `base_url`, `project_keys` | Atlassian MCP `getAccessibleAtlassianResources` → `getVisibleJiraProjects` |
| `linear` | `team_keys` | Linear API if available; else ask |
| `github_issues`, `github` | `repos` (list of `owner/name`) | `gh repo list <owner> --limit 100 --json nameWithOwner` |
| `gitlab` | `base_url`, `projects` | Ask |
| `local_repos` | `paths` (abs) | Ask, verify each is a git repo |
| `slack` | `channels` | Slack MCP `slack_search_channels` |
| `gmail` | `query` | Suggest examples (`from:boss newer_than:7d`) |
| `confluence` | `base_url`, `spaces` | Atlassian MCP `getConfluenceSpaces` |
| `notion` | `database_ids` and/or `page_ids` | Ask |
| `gdrive_docs` | `folder_ids` | Drive MCP if connected; else ask |
| `gdrive_gemini` | `folder_ids` (optional), `name_filter`, `days_back`, `max_files` | Ask, defaults: `name_filter="Notes by Gemini"`, `days_back=30`, `max_files=50` |
| `gcal` | `calendar_ids`, `days_back`, `days_ahead` | Calendar MCP if connected; defaults `["primary"]`, 7, 14 |
| `obsidian` | `vault_path` (abs) | Ask, verify directory exists |
| `markdown_dirs` | `paths` (list of abs dirs) | Ask, verify each exists |
| `readwise` | (none) | Just enable |
| `rss` | `feeds` (URL list) | Ask |
| `http` | `endpoints` (list of `{name, url, auth_env, parser}`) | Ask per endpoint |

Concrete dialogue examples:

**jira**:
> jira는 `base_url`과 `project_keys`가 필요합니다.
>
> 1) base_url 알려주세요 (예: `https://yourcorp.atlassian.net`):
>
> [user pastes] → Atlassian MCP가 붙어있어요. 추적 가능한 프로젝트 목록 받아올까요? (y/n)
>
> [if yes, call getAccessibleAtlassianResources + getVisibleJiraProjects, render]
>
> 2) 추적할 프로젝트 키들 골라주세요 (번호/이름, 다중 OK):

**markdown_dirs**:
> `markdown_dirs`는 `paths` 배열만 필요합니다 (절대경로).
>
> 어느 디렉토리들 추적할까요? 한 줄에 하나씩 또는 콤마로:
>
> [user types] → 검증 중... ✓ 3개 모두 존재
>
> (혹시 1개 존재 안 하면) ✗ `/home/x/missing` — 디렉토리가 없네요. 다른 경로?

**github_issues**:
> github_issues는 `repos` 목록(owner/name 형태)이 필요합니다.
>
> `gh repo list ToySin --limit 50` 돌려서 메뉴로 뽑아드릴까요? 아니면 직접 입력?
>
> [user picks from menu]

### 3.4 Aggregate env-var requirements

After all sources are done, list the `auth_env` references they need.
Read the workspace's `.env` (if it exists) and split into "already
set" vs "missing":

> 활성화한 소스들이 필요로 하는 환경변수:
>
> ✓ 이미 `.env`에 있는 것:
>   - `GITHUB_TOKEN`
>
> ✗ 추가해야 하는 것 (파일에 직접 넣어주세요):
>   - `JIRA_TOKEN=...`
>   - `JIRA_EMAIL=...`
>
> ⚠️ 시크릿은 제가 `.env`에 직접 안 씁니다. 위 라인들을 직접 추가해주세요.

### 3.5 Show the diff and confirm

Render the YAML changes you're about to make (a unified diff, or the
section that changes). Wait for explicit y/n.

> sources.yaml 변경 미리보기:
>
> ```diff
>   jira:
> -   enabled: false
> +   enabled: true
> -   base_url: ""
> +   base_url: "https://yourcorp.atlassian.net"
> -   project_keys: []
> +   project_keys: ["ACS", "SYS"]
>     auth_env: JIRA_TOKEN
> ```
>
> 적용할까요? (y/n)

If `n`, ask which part to revise and loop back inside Branch 3.
If `y`, write the file.

### 3.6 Wrap up the configure branch

After writing:

> ✓ `<workspace>/sources.yaml` 갱신됨
>
> 다음 단계:
> 1. `<workspace>/.env`에 위 환경변수 추가
> 2. ETL 실행: `python -m library.sources.run`
> 3. (선택) L2 enrichment: `python -m library.enrichment`

---

## Branch 4 — Status check

Gather and report all of these in one tidy block:

1. **Active workspace** — `assisthub current`
2. **Enabled sources** — parse `sources.yaml`, list `enabled: true` ones
3. **Required env vars** — for each enabled source's `auth_env`, mark
   ✓ if set in `<workspace>/.env`, ✗ if missing
4. **Last sync per source** — read `<workspace>/sync_state.json`,
   render as `source: <iso-timestamp>` (or "(never)")
5. **Exports state** — count rows in `<workspace>/exports/graph/*.jsonl`
6. **Recommendation** — if any source has missing env var, say so. If
   sync_state is stale (>1 day), suggest re-running ETL. Otherwise
   say everything looks healthy.

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

---

## Hard rules (apply to all branches)

- **Never write to `.env`.** Credentials stay in the user's hands —
  print the lines they need to add and stop. Even if asked, refuse and
  remind them why.
- **Never blank out a source the user didn't touch this session.** If
  jira was enabled with config and the user didn't pick jira this time,
  leave jira alone.
- **Preserve file structure.** Keep category comments, the `auth_env`
  pointer style, and field ordering as they were in the template.
- **Validate before recording.** Path doesn't exist → ask again. URL
  unreachable → flag it (don't fail, but tell the user).
- **One source / one field at a time.** Don't ask 5 things in one block.
- **Bail gracefully.** If the user says "skip" / "cancel" / "stop",
  acknowledge and exit without writing.

## When to fall back from a discovery tool

If an MCP / CLI tool errors out (auth missing, network, etc.), do
*not* loop on retries. Tell the user briefly, then ask them to type
the value manually. Note in summary: "Atlassian MCP not available, `project_keys` entered manually".
