# /ws-config — Workspace lifecycle (create / switch / configure / status)

Single conversational entry point for everything workspace-related.
Show the menu, wait for the choice, delegate to the matching branch
file. Each branch is a separate skill document under
`.claude/skills/ws-config/` so they stay focused.

Hard rules apply to every branch — read
`.claude/skills/ws-config/_rules.md` once at the start and keep them
in mind throughout the conversation.

## 1. Open

Gather state to render an accurate menu:

```bash
~/repositories/assistant-hub/scripts/assisthub list 2>/dev/null    # workspaces (* marks active)
~/repositories/assistant-hub/scripts/assisthub current 2>/dev/null # active name
```

Render:

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

## 2. Delegate

Wait for the choice. Then read the matching file and execute it:

| Choice | Read this |
|--------|-----------|
| 1 | `.claude/skills/ws-config/create.md` |
| 2 | `.claude/skills/ws-config/switch.md` |
| 3 | `.claude/skills/ws-config/configure-sources.md` |
| 4 | `.claude/skills/ws-config/status.md` |
| 5 | acknowledge and exit |

If the user types something ambiguous, re-show the menu.

## 3. Loop

After a branch finishes, ask:

> 또 뭐 도와드릴까요? (메뉴 다시 보기 / 끝)

If they want more, return to step 1. Otherwise close out.
