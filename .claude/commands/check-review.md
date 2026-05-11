# /check-review — Brief PR status and route to action

Inventory my open PRs + review-requested PRs, classify each, and
hand off to the right downstream skill (`/apply-review`, fix flow,
merge, wait).

## Args

| Arg | Behavior |
|-----|----------|
| (none) | Full briefing → branch (Steps 1-3) |
| `pending` | Show pending review comments only (Step 4) |
| `history` | Last 20 processed comments from history |
| `clear` | Reset `review-history.yaml` (with confirmation) |

## Step 1. PR Briefing

```bash
gh pr list --author "@me" --state open --json number,title,url,headRefName,mergeable,reviewDecision,statusCheckRollup,repository
gh search prs --review-requested @me --state open --json number,title,url,repository
```

If a default repo is configured for this workspace (e.g.,
`<workspace>/dashboard.yaml` lists projects), scope `gh pr list` to
those repos. Otherwise fall back to the user's full open-PR set.

## Step 2. Classify

For each of *my* open PRs, assign one label:

| Label | Condition |
|-------|-----------|
| `🔧 fix` | CI failed OR merge conflict |
| `📝 review` | `reviewDecision == CHANGES_REQUESTED` OR has unanswered review comments |
| `✅ merge` | `reviewDecision == APPROVED` AND CI passing |
| `⏳ wait` | `reviewDecision == REVIEW_REQUIRED` AND CI passing/pending |

Render:

```
## My open PRs

| # | PR | Label | Summary |
|---|-----|-------|---------|
| 1 | <repo>#1234 [TICKET] Title | 📝 review | 2 unanswered comments |
| 2 | ...
```

If review-requested set is non-empty, show separately:

```
## Review requested
- N PRs waiting for your review (list)
```

Ask: "어느 PR을 다루실까요? (번호 또는 라벨)"

## Step 3. Branch

Based on the selected PR's label:

| Label | Action |
|-------|--------|
| `📝 review` | Hand off to `/apply-review <pr-url>` from its Step 2 onward |
| `🔧 fix` | Step into a fix subflow: check out the branch (`gh pr checkout`), investigate (`gh pr checks`, `gh pr diff`), propose fix, apply on approval |
| `✅ merge` | Confirm with the user, then `gh pr merge --squash` (default) — never auto-merge without explicit `y` |
| `⏳ wait` | No action; offer to ping reviewers if blocking |

## Step 4. `pending` mode — review comments detail

```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate --jq '
  [.[] | select(.in_reply_to_id == null)
       | {id: .id, user: .user.login, path: .path, line: .line, body: .body}]
'
```

Filter out comments whose `id` is in
`<workspace>/review-history.yaml` `entries[].comment_id`. The
remaining are unanswered. List them with:

- file:line
- reviewer
- 1-line excerpt
- comment id (so the user can refer to specific ones)

## Step 5. `history` / `clear`

```bash
# Last 20 processed comments
python -m library.review_history history

# Wipe all history (confirm before running)
python -m library.review_history clear
```

`pending` mode also uses `library.review_history.seen_comment_ids()` to
filter out already-handled comments. No manual file management needed.

## Notes

- Treat `review-history.yaml` as gitignored locally in the workspace
  (it leaks reviewer identities and comment text otherwise).
- `bot[*]` reviewers (CI bots, dependabot) are noisy — skip them by
  default in `pending` mode, surface only if `--include-bots` is passed.
