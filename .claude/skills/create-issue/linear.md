# create-issue / linear

Create a Linear issue via the GraphQL API.

## Step 1. Find team + project

```bash
python -c "
from library.sources.config import load
s = {src.name: src for src in load()}['linear']
print('team_keys:', s.settings.get('team_keys'))
import os; print('token set:', bool(os.environ.get('LINEAR_API_KEY') or s.auth))
"
```

Query Linear for teams and optional project to attach to:
```graphql
query {
  teams { nodes { id key name } }
}
```

## Step 2. Resolve assignee (optional)

```graphql
query { viewer { id name email } }
```

## Step 3. Draft + confirm

Show:
```
Team:        <key>
Title:       <title>
Description: <description>
Project:     <name or none>
Assignee:    <name or unassigned>
Priority:    0 (none) / 1 (urgent) / 2 (high) / 3 (medium) / 4 (low)
```

Wait for explicit approval.

## Step 4. Create

```graphql
mutation CreateIssue($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { identifier title url }
  }
}
```

Variables:
```json
{
  "input": {
    "teamId": "<team.id>",
    "title": "<title>",
    "description": "<description>",
    "assigneeId": "<viewer.id or null>",
    "projectId": "<project.id or null>",
    "priority": 0
  }
}
```

POST to `https://api.linear.app/graphql` with
`Authorization: <LINEAR_API_KEY>`.

Print the returned `identifier` (e.g. `ENG-42`) and `url`.
