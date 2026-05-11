# /create-issue — Create a tracked work item in the workspace tracker

Single entry point for creating issues/tickets regardless of which
tracker the workspace uses (Jira, Linear, or GitHub Issues). Detects
the backend from `sources.yaml` and delegates to the matching sub-skill.

## 1. Detect backend

```bash
python -c "
from library.sources.config import load
sources = {s.name: s for s in load()}
backends = [n for n in ('jira', 'linear', 'github_issues') if n in sources]
print(backends)
"
```

Pick the first enabled backend. If multiple are enabled, ask the user
which one to target before proceeding.

## 2. Collect inputs

Ask for (or use args if provided):
- **Title** — one concise line
- **Description** — what/why/acceptance criteria (may be empty)
- **Project / Epic** — offer a list from the graph:
  ```bash
  python -c "
  from graph import builder
  from library.graph_queries import project_overview
  db = builder.connect()
  for p in project_overview(db): print(p.key, p.name)
  "
  ```
- **Assignee** — default to self (omit to leave unassigned)
- **Labels / priority** — optional, backend-specific

## 3. Delegate to backend sub-skill

| Detected backend | Sub-skill |
|---|---|
| `jira` | `.claude/skills/create-issue/jira.md` |
| `linear` | `.claude/skills/create-issue/linear.md` |
| `github_issues` | `.claude/skills/create-issue/github.md` |

Load the sub-skill and follow its steps to create the issue.

## 4. Post-create

After the issue is created:
1. Print the issue URL / key.
2. Offer: "대시보드 action_items에 추가할까요?" — if yes, append to
   `dashboard.yaml` action_items.
3. Offer: "graph에 지금 넣을까요?" — if yes, run:
   ```bash
   python -m library.sources.run --source <backend>
   ```

## Notes

- Never create issues silently — always show the draft to the user
  and wait for a "go" before calling the API.
- If the workspace has no tracker configured (only markdown_dirs),
  create a `notes/<slug>.md` file and inform the user it won't be
  tracked externally.
