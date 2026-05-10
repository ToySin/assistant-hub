# /ws-config — Branch 3: Configure data sources

Walk through enabling and configuring data sources for the active
workspace. Re-runnable; safe to invoke any time. **One source / one
field at a time, validate, then move on.**

Always-applicable rules: see `.claude/skills/ws-config/_rules.md`.

## 1. Read current state

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

## 2. Pick categories

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

## 3. Per-source field map and discovery hints

For each chosen source, ask only the required fields, validate where
possible, and remember the answers in working memory. **Don't touch
the file yet.**

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

## 4. Concrete dialogue examples

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

## 5. Aggregate env-var requirements

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

## 6. Show the diff and confirm

Render the YAML changes as a unified diff. Wait for explicit y/n.

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

If `n`, ask which part to revise and loop. If `y`, write the file.

## 7. Validate auth + connectivity (probe each enabled source)

After the user confirms the env-var setup is done (or wants to proceed
even with some missing), run the smoke probe so the first ETL doesn't
surface 6 different breakages 30 minutes in:

```bash
python -m library.sources.validate
```

The probe:
- Hits each source's auth endpoint with one minimal call
- Returns `[OK]` or `[FAIL]` per source with a specific actionable
  error (not "something went wrong"). Examples of what it catches:
  jira 401 with bad token, confluence 404 on missing space key, gh
  CLI not authenticated, gcloud ADC missing drive scope, markdown
  paths that don't exist.

If everything passes, proceed to Step 8. If any failure:

> [FAIL] gdrive_gemini: Drive API returned 403...
>
> 이 부분 고치고 진행하실래요, 아니면 일단 그대로 두고 다른 source ETL만 돌릴까요?

The user picks. If they fix and want re-probe, re-run validate.

## 8. Wrap up

> ✓ `<workspace>/sources.yaml` 갱신됨
> ✓ N개 source 검증 통과 (또는 M개 통과 / K개 보류)
>
> 다음 단계:
> 1. ETL 실행: `python -m library.sources.run`
> 2. (선택) L2 enrichment: `python -m library.enrichment`
