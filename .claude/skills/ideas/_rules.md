# Hard rules — apply to every /idea branch

- **Capture must be ≤2 turns.** Take the text, write the file, report
  the path. Do NOT ask refining questions inside capture — that's
  what `/idea refine` is for.
- **Never auto-promote.** Promotion always needs an explicit user ask.
  Even if a captured idea looks "ready", just leave it in `captured`.
- **Never edit a `promoted` idea without confirmation.** The
  GitHub issue is the canonical place once promoted. Show a warning
  and ask before changing the markdown.
- **Frontmatter is canonical.** When the user edits the file directly,
  trust their changes — don't overwrite their fields. When this skill
  edits, only touch the field(s) the action is responsible for.
- **One question at a time during refine.** Don't dump a 5-question
  block; ask the most useful one first and follow up only if needed.
- **Bail gracefully.** If the user says "skip" / "cancel" / "stop",
  acknowledge and exit without writing.

## Storage

- Path: `<workspace>/notes/ideas/<YYYY-MM-DD>-<slug>.md`
- Frontmatter fields: `title`, `status`, `captured_at`, `effort`,
  `tags`, `related`, `promoted_to`, `promoted_at`
- Status state machine: `captured → refined → promoted`. No going back.

## Auto-trigger

The agent should propose `/idea capture` (not silently run it) when the
user mentions a future improvement or proto-task in passing — phrases
like "이런 거 있으면 좋겠다", "나중에 ~ 해보자", "improvement 하나",
"~를 추가하면 어떨까". Always confirm before writing.
