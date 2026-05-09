# /idea capture — Fast capture

Goal: get the user's idea on disk in the next 30 seconds. Don't
interrogate them.

## Procedure

### Step 1. Write the file

```bash
ASSISTHUB_WORKSPACE=<active> \
  python -m library.ideas capture "<freeform text from the user>"
```

Pass the user's exact wording as the argument. The helper auto-derives
title and slug. It prints the path of the new markdown file.

If the user volunteered a title, pass `--title "<title>"` too.

### Step 2. Refresh the graph (best-effort)

If the workspace has `markdown_dirs` enabled with `notes/ideas/` (or a
parent of it) in its paths:

```bash
ASSISTHUB_WORKSPACE=<active> python -m library.sources.run --source markdown_dirs
```

Don't fail capture if this errors — the file is the source of truth,
ETL can catch up later. Just note it in the report.

### Step 3. Report

Tell the user, in one line:
- Path of the new file
- Status: `captured`
- Whether the graph picked it up

Then offer the next step:

> 더 다듬으시려면 `/idea refine <slug>`,
> 바로 GitHub 이슈로 발행하시려면 `/idea promote <slug> --repo <owner/name>`.

That's the whole capture — do not ask for effort/tags/related here.
Refinement happens in `/idea refine`.

## Gotchas

- If `notes/ideas/` doesn't exist yet the helper creates it.
- If `markdown_dirs` source isn't enabled, the file still lives on
  disk but won't be in the graph until the user enables it. Mention
  this once, don't loop on it.
