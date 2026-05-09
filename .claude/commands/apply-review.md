# /apply-review — End-to-end PR review processing

Analyze reviewer comments, **apply code changes**, and post replies.
Lightweight reply-only version is `/reply-pr`. To pick a PR and route,
use `/check-review`.

## Args

| Arg | Behavior |
|-----|----------|
| (none) | Auto-pick from my open PRs with unanswered review comments |
| PR number or URL | Target the specified PR (auto-extract repo from URL) |

## Step 1. Select PR

If args provided → use directly. Otherwise:

```bash
gh search prs --author "@me" --state open --review changes_requested \
  --json number,title,url,repository
```

Pick PRs with at least one unanswered top-level comment. If 1, auto-select.
If multiple, show list and ask. If 0, exit with "No pending review."

## Step 2. Collect unanswered comments

```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate
```

Author of the PR:

```bash
gh api repos/<owner>/<repo>/pulls/<n> --jq '.user.login'
```

A top-level comment is unanswered when:
- `in_reply_to_id` is null
- AND no reply by the PR author exists in the same thread

Then exclude any whose `id` is in
`<workspace>/review-history.yaml` `entries[].comment_id`. If the file
doesn't exist, treat all top-level unanswered comments as new (history
is created on first commit in Step 6).

## Step 3. Intent analysis + change plan

For each unanswered comment, in this order:

1. Read the file at the comment's `path` and `line` (use the
   `diff_hunk` for context if the line has shifted).
2. Classify intent:
   - `change_request` — code change asked for
   - `nit` — minor style / naming
   - `question` — explanation requested
   - `discussion` — opinion / design exchange
3. Draft action:
   - `change_request` / `nit` → specific code change
   - `question` → draft answer
   - `discussion` → draft response

Show the user a single combined plan:

```
## PR <repo>#<n> — apply plan

### 1. [<intent>] <reviewer> on <path>:<line> (id:<comment_id>)
> <quoted comment, ~80 chars>

**Intent**: <classification>
**Plan**: <change or draft>

### 2. ...
```

## Step 4. Approval

Ask: "전체 적용할까요? 선택만 적용하려면 번호 (예: 1,3)."

## Step 5. Apply code changes

For each approved `change_request` / `nit`, use Edit/Write to apply.
Group commits sensibly — one commit per logical change is OK; squash
into a single "address review" commit only if the user asks.

Run any obvious validation (linter / formatter / build) the workspace
already documents. Don't invent a CI loop.

## Step 6. Post replies

For each approved comment, post a reply via:

```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments \
  -f body='<reply text>' \
  -F in_reply_to=<comment_id> \
  -X POST
```

Reply tone:
- `change_request` → "Fixed in <commit-sha>: <one line of what changed>"
- `nit` → same, briefer
- `question` → answer directly, cite code if useful
- `discussion` → respond to the point, no need to "resolve"

## Step 7. Record history

Append to `<workspace>/review-history.yaml`:

```yaml
entries:
  - pr: <owner>/<repo>#<n>
    comment_id: <id>
    intent: <classification>
    action: applied | answered | declined
    commit: <sha>          # for applied changes only
    processed_at: <ISO 8601 UTC>
```

Create the file with `entries: []` if missing. Append, don't rewrite.

## Step 8. Push (optional)

If commits were made, ask: "push할까요?" — never auto-push.

If pushed, note the new commit URL in chat. Don't auto-merge even
when CI is green; that's a separate `/check-review` decision.

## Step 9. Suggest /save (if learning surfaced)

If processing the review revealed something durable — a non-obvious
convention the reviewer enforced, a recurring style nit worth
codifying, a domain mapping you didn't know — propose `/save` before
ending:

> 이번 리뷰에서 ~ 학습한 게 있는데 `knowledge/<name>.md`에 정리할까요?

Skip silently if the review was mechanical (typos, formatting only).

## Notes

- One-line invariant: **never run `gh pr merge` from this skill**. This
  skill applies and replies; merge is its own deliberate step.
- If a comment thread already has an author reply that says "fixed in
  <sha>" or similar, treat it as resolved and skip — don't double-post.
- For batches of `nit`-only comments, offer to apply all in one commit
  with a brief "Address review nits" message.
