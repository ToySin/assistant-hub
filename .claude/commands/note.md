# /note — Append a quick note to the workspace's rolling log

Lightweight log entry — no structure beyond date + bullet. For
proto-tasks worth tracking (effort, related, may become an issue),
use `/idea capture` instead.

## Args

| Arg | Behavior |
|-----|----------|
| (text) | Use the text as the note body |
| (none) | Ask the user for the note |

## Procedure

### Step 1. Resolve target file

```bash
NOTES=$(python -c 'from library.workspace import get_workspace_path; print(get_workspace_path() / "notes.md")')
```

### Step 2. Append

Format:

```
## YYYY-MM-DD

- <note content>
```

- If today's `## YYYY-MM-DD` header already exists, append a `- <note>`
  bullet under it. Don't add a duplicate header.
- If the file doesn't exist, create it with `# Notes` at the top, then
  the date header and entry.
- Multi-line notes: indent continuation lines with 2 spaces under the
  bullet. Don't break list parsing.

### Step 3. Confirm

Echo the appended bullet back to the user in one line. Stop.

## Notes

- Don't truncate user-provided content. Notes are theirs.
- Don't run any ETL — markdown_dirs picks notes.md up on the next
  scheduled refresh, no need for a manual sync here.
- If the note clearly is a TODO ("나중에 X 해보자"), propose `/idea
  capture` first, fall back to plain note if the user prefers.
