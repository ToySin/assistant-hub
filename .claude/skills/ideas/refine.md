# /idea refine — Fill in the gaps

Goal: turn a raw capture into something promote-ready. Conversational,
incremental, low-pressure. The user can always type "skip" to stop.

## Procedure

### Step 1. Locate the file

The user gave a slug (or filename). Resolve to the markdown:

```bash
ls "$(ASSISTHUB_WORKSPACE=<active> python -c '
from library.ideas import ideas_dir
print(ideas_dir())
')"/<slug>*.md
```

If multiple match, ask which one. If none, suggest `/idea list` to
see what's there.

### Step 2. Read state

Read the file. Check frontmatter status:

- `captured` → proceed.
- `refined` → tell the user it's already refined, ask if they want to
  re-refine; proceed only on yes.
- `promoted` → **stop**. Show a warning ("이미 GitHub 이슈로 발행됨:
  <url>"). Edit only with explicit confirmation, and document the
  reason in the body.

### Step 3. Ask one missing field at a time

Look at frontmatter. Ask, in this order, only for fields that are
unset / empty:

1. **Why** — what problem does this solve / why now?
   (Updates the `## Why` section in the body.)
2. **Effort** — `S | M | L`. Rough day-feel.
3. **Tags** — 1–3 short tags (auto-sync, briefing, etc.).
4. **Related** — existing Issues, Concepts, or other ideas this
   touches. Free-form list. Suggest format `github:<owner>/<repo>#N`
   or `concept:<name>`.

After each answer, write the file back. Don't batch — incremental
saves means a stop in the middle still preserves progress.

### Step 4. Mark refined

When the body's `## Why` is filled and effort/tags are set, set
`status: refined` in the frontmatter and write.

### Step 5. Offer next step

> 발행 준비됐다 싶으면 `/idea promote <slug> --repo <owner/name>`.

Don't auto-promote. Refining and promoting are deliberately separate.

## Gotchas

- If the user types "skip" mid-refine, save what's already filled and
  exit. Don't reset previously set fields.
- Use the `Edit` tool for in-place YAML/markdown edits to keep diffs
  clean. Avoid full rewrites that re-order fields.
