# /idea promote — Publish as a GitHub issue

Goal: turn an idea markdown into a real, tracked GitHub issue, and
keep the lineage in the graph.

## Procedure

### Step 1. Confirm target repo

The user must specify `--repo <owner/name>`. If they didn't, ask.
Default suggestion: the active workspace's repo
(`ToySin/assisthub-ws-<workspace>`).

### Step 2. Pre-flight check

```bash
ASSISTHUB_WORKSPACE=<active> python -m library.ideas list
```

Confirm the slug exists, isn't already promoted (frontmatter
`status: promoted` + `promoted_to` set). If already promoted, return
the existing URL and stop.

If `status` is still `captured` (not `refined`), warn the user — body
will be skinny — and ask whether to refine first or push as-is.

### Step 3. Promote

```bash
ASSISTHUB_WORKSPACE=<active> \
  python -m library.ideas promote <slug> --repo <owner/name>
```

This single call:
- Reads the markdown
- Builds an issue body that includes the body sections plus an
  `Effort / Tags / Related` footer when those are filled
- Calls `gh issue create` and captures the URL
- Updates frontmatter (`status: promoted`, `promoted_to: <url>`,
  `promoted_at: <ts>`)
- Re-runs the relevant ETLs (`markdown_dirs`, `github_issues`) so
  the new GitHub Issue and the now-updated Note are both in the graph
- Adds the lineage edge: `Issue -> extracted_from -> Note`

It prints the issue URL on success.

### Step 4. Report

Show:
- The issue URL (clickable)
- Confirmation that the markdown is now `promoted`
- Confirmation that the lineage edge was created

Suggest follow-ups only if useful — e.g., "now run `/briefing` to see
it land in the open list".

## Gotchas

- If `gh` isn't authenticated for the target repo, the helper raises.
  Tell the user to run `gh auth login` and retry.
- If `markdown_dirs` or `github_issues` aren't enabled on the
  workspace, the helper still creates the GitHub issue but skips the
  graph update. Surface that in the report.
- Don't manually run `gh issue create` here — the helper does the
  whole flow atomically. Calling `gh` directly would skip the
  frontmatter update and the lineage edge.
