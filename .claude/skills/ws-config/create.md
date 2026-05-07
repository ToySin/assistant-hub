# /ws-config — Branch 1: Create new workspace

Conversational workspace bootstrap. Validate inputs, run the script,
then offer to roll into source configuration immediately.

Always-applicable rules: see `.claude/skills/ws-config/_rules.md`.

## 1. Gather inputs

> 워크스페이스 이름 (소문자/숫자/대시, 알파넘으로 시작):

Validate against `^[a-z0-9][a-z0-9-]*$`. If invalid, restate the rule
and ask again. If `~/repositories/assisthub-ws-<name>/` already exists,
say so and bail back to the main menu.

> GitHub에 private 레포로 푸시할까요? (y/n, 기본 y)
> [if y] GitHub owner는 `<현재 gh user>` 그대로 갈까요? (y/n)

## 2. Run the bootstrap script

```bash
~/repositories/assistant-hub/scripts/new-workspace.sh <name>           # default = push
~/repositories/assistant-hub/scripts/new-workspace.sh <name> --no-push # local only
~/repositories/assistant-hub/scripts/new-workspace.sh <name> --owner <gh-owner>
```

The script handles: directory copy from `templates/workspace/`,
`{{WORKSPACE_NAME}}` substitution, `git init`, hook install, slash
command symlink install, initial commit, and (if pushing) `gh repo
create --private --push`.

Report back:
- Local path
- GitHub URL (if pushed)

## 3. Set as active

> 방금 만든 `<name>`을 활성으로 설정할까요? (y/n)

If yes:

```bash
~/repositories/assistant-hub/scripts/assisthub use <name>
```

## 4. Roll into source configuration

> 새 워크스페이스에 데이터 소스도 지금 설정할까요? (y/n)

If yes, read `.claude/skills/ws-config/configure-sources.md` and
execute it with the new workspace as the target.

If no, stop and remind them they can run `/ws-config` again later.
