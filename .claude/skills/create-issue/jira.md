# create-issue / jira

Create a Jira issue using the Atlassian MCP server or gh-equivalent REST calls.

## Step 1. Find the project + issue type

```bash
# List Jira projects visible to this token
python -c "
from library.sources.config import load
s = {src.name: src for src in load()}['jira']
print('base_url:', s.settings.get('base_url'))
print('project_keys:', s.settings.get('project_keys'))
"
```

Use the MCP `getJiraProjectIssueTypesMetadata` tool to list issue types
for the target project key. Prefer "Story" or "Task" for regular work;
"Bug" for defects. Ask the user if unclear.

## Step 2. Find epic (optional)

```bash
# Open epics in the target project
python -c "
from graph import builder
db = builder.connect()
rows = db.query(
  \"SELECT external_key, title FROM Issue \"
  \"WHERE source='jira' AND status_category IN ['new','indeterminate'] \"
  \"AND CONTAINS(string::lowercase(title), 'epic') LIMIT 20;\"
)
for r in rows: print(r['external_key'], r['title'])
"
```

Ask which epic to link under, or leave blank.

## Step 3. Draft + confirm

Show the user:
```
Project:     <key>
Type:        Story / Task / Bug
Title:       <title>
Description: <description>
Epic:        <key or none>
Assignee:    <name or unassigned>
```

Wait for explicit approval before calling the API.

## Step 4. Create via MCP

Use `createJiraIssue` (Atlassian MCP tool):
```
project:     <project key>
summary:     <title>
description: <description>
issuetype:   <type name>
[epic_link:  <epic key>]
[assignee:   <account_id from lookupJiraAccountId>]
```

Print the returned issue key and URL.

## Step 5. Transition (optional)

If the user wants to immediately move it to "In Progress":
Use `getTransitionsForJiraIssue` then `transitionJiraIssue`.
