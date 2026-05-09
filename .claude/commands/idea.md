# /idea — Capture, refine, and promote ideas

Lightweight pipeline for proto-tasks: a thought worth saving but not
yet an issue.

## When to use proactively

Watch for the user mentioning a future improvement or proto-task in
passing — phrases like "이런 거 있으면 좋겠다", "나중에 ~ 해보자",
"improvement 하나", "~ 추가하면 어떨까", "나중에 issue로 뽑자".

When you see one, **propose** capturing it before the conversation
moves on:

> 이거 idea로 캡처해둘까요? (`/idea capture`)

Don't silently capture. Always ask. Then run `/idea capture` if they
say yes.

## Subcommands

| Subcommand | What it does | Skill file |
|------------|--------------|------------|
| `capture <text>` | Write a new idea markdown file (≤2 turns) | `.claude/skills/ideas/capture.md` |
| `refine <slug>` | Fill in why / effort / tags / related, one question at a time | `.claude/skills/ideas/refine.md` |
| `promote <slug> --repo <owner/name>` | Open a GitHub issue from the idea, link it back to the originating Note | `.claude/skills/ideas/promote.md` |
| `list` | List captured ideas with status | (run `python -m library.ideas list`) |

Read `.claude/skills/ideas/_rules.md` once at the start and keep its
hard rules in mind throughout. Hand off to the matching skill file
based on what the user asked for.

## Default repo

When the user doesn't specify `--repo` for `promote`, suggest the
active workspace's GitHub repo (`ToySin/assisthub-ws-<workspace>`)
before falling back to asking.
