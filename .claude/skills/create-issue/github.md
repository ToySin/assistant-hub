# create-issue / github

Create a GitHub Issue via gh CLI.

## Step 1. Find repo

```bash
python -c "
from library.sources.config import load
s = {src.name: src for src in load()}['github_issues']
print('repos:', s.settings.get('repos'))
"
```

If multiple repos, ask which one.

## Step 2. Find labels / milestone (optional)

```bash
gh label list --repo <owner/repo> --limit 30
gh milestone list --repo <owner/repo>
```

## Step 3. Draft + confirm

Show:
```
Repo:        <owner/repo>
Title:       <title>
Body:        <description>
Labels:      <labels or none>
Assignee:    <@me or blank>
```

Wait for explicit approval.

## Step 4. Create

```bash
gh issue create \
  --repo <owner/repo> \
  --title "<title>" \
  --body "<description>" \
  [--label "<label>"] \
  [--assignee "@me"]
```

Print the returned issue URL.
