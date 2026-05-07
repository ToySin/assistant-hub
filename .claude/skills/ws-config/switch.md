# /ws-config — Branch 2: Switch active workspace

Always-applicable rules: see `.claude/skills/ws-config/_rules.md`.

## 1. List workspaces

```bash
~/repositories/assistant-hub/scripts/assisthub list
```

Render as a numbered list with the asterisk on the current active.

## 2. Wait for choice

Accept a number, a name, or a substring match. If the choice is
ambiguous (multiple matches) or unknown, restate the list and ask again.

## 3. Switch

```bash
~/repositories/assistant-hub/scripts/assisthub use <name>
```

## 4. Confirm

Read back the new active and ask if that's what they expected. If they
say "no" or pick something else, loop.
