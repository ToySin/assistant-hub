# /runbooks — Self-reinforcing automation recipes

A runbook is `(pattern → steps)` that walks an automation ladder
(`manual → semi-auto → auto`) as evidence of success or failure
accumulates. Each branch below is a separate skill document under
`.claude/skills/runbooks/` so they stay focused.

For background — what a runbook is, the lifecycle ladder, pattern
fields, substitution variables, dedup, storage caveats — read
`.claude/skills/runbooks/_spec.md` once at the start. Every branch
assumes you've read it.

## 1. Open

> 뭐 하시려고요?
>
> 1. 기존 runbook 둘러보기 (list / view / policies)
> 2. 최근 이벤트로 새 runbook 만들기
> 3. 특정 이벤트에 매칭되는 runbook 찾기 (match / render)
> 4. 실행 결과 기록 또는 삭제 (record / delete)
> 5. 취소

## 2. Delegate

| Choice | Read this |
|--------|-----------|
| 1 | `.claude/skills/runbooks/browse.md` |
| 2 | `.claude/skills/runbooks/create.md` |
| 3 | `.claude/skills/runbooks/match.md` |
| 4 | `.claude/skills/runbooks/outcome.md` |
| 5 | acknowledge and exit |

If the user types something specific like "show me runbook 7" or
"create one for event 42" without picking from the menu, route them
to the right branch directly without re-asking.

## 3. Loop

After a branch finishes, ask if there's anything else. If yes, return
to the menu. If no, close out.
