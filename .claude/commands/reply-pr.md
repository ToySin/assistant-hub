# /reply-pr — Lightweight reply to PR review comments (no code changes)

Use when the response is *only* text — already-applied work, an answer
to a question, or follow-up guidance. For code-change + reply
together, use `/apply-review`.

## When to pick which

| Scenario | Skill |
|----------|-------|
| Reply only (already applied / question / follow-up) | **`/reply-pr`** |
| Code change + reply | `/apply-review` |
| Status check + route | `/check-review` |

## Args

- PR number or URL (required)
- `-r <repo>` (optional, infer from URL if given)

## Step 1. Resolve target

If a URL is provided:
- `owner/repo` and `number` extracted from
  `https://github.com/<owner>/<repo>/pull/<n>`

Else with `-r <repo>` and a number, use those.

If neither, ask once.

## Step 2. Pull unanswered comments

```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate
```

Filter:
- `in_reply_to_id` == null
- No reply by PR author in thread
- `id` not in `<workspace>/review-history.yaml`

If 0, exit "no pending replies".

## Step 3. Draft per comment

For each unanswered comment:

1. Read the file at `path:line` for context.
2. Classify briefly: `applied` (you/the user already did the change), `question` (asks for explanation), `discussion`.
3. Draft a reply, 1-3 sentences. Cite a commit sha if the change is already in.

Show the full set together:

```
## PR <repo>#<n> — replies (3)

### 1. <reviewer> on <path>:<line> (id:<id>)
> <quoted>
**Reply**: <draft>
```

## Step 4. Approve

Ask which to send (`all` / `1,3` / `cancel`).

## Step 5. Post

```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments \
  -f body='<draft>' \
  -F in_reply_to=<comment_id> \
  -X POST
```

## Step 6. Record history

Same shape as `/apply-review` — append `entries[]`:

```yaml
- pr: <owner>/<repo>#<n>
  comment_id: <id>
  intent: <applied|question|discussion>
  action: answered
  processed_at: <ISO 8601 UTC>
```

## Step 7. Report

One line per posted reply: comment id + URL.

## Notes

- This skill never edits code or runs `gh pr merge`.
- If a reply needs a code change, abort and route the user to
  `/apply-review`.
- Bot comments (e.g., `dependabot[bot]`) are skipped unless explicitly
  included via `--include-bots`.
