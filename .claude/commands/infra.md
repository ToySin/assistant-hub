# /infra — Preload infra context before infrastructure work

Pull the workspace's infrastructure-relevant static files into context
so subsequent steps don't ad-hoc explore the repo.

## Where context lives

Workspace static surface (read whichever exist):

| File | Domain |
|------|--------|
| `<workspace>/infrastructure.md` | GCP / cluster / domain topology |
| `<workspace>/knowledge/*.md` | Domain-specific notes |
| `<workspace>/runbooks/*.md` | Operational recipes |
| `<workspace>/runbooks/case-studies.md` | Cause / symptom / diagnosis pattern catalog |
| `<workspace>/runbooks/postmortems/*.md` | Incident write-ups |
| `<workspace>/universe/*.yaml` | Service inventory / deploy / autoscaling |

If a file is missing, note it but proceed. Don't fabricate content.

## Procedure

### Step 1. Identify the user's intent

From args or conversation, determine the work type:

| Intent keywords | Files to load |
|-----------------|---------------|
| Incident, debug, status check, access issue, 502 | `infrastructure.md`, `runbooks/case-studies.md`, recent `runbooks/postmortems/` |
| Deploy, scaling, terraform, k8s manifest | `infrastructure.md`, `universe/` |
| Service relationship, dependency, fanout | `universe/`, `infrastructure.md` |
| New service, capacity planning | `universe/`, `infrastructure.md`, applicable runbooks |

When unclear, ask once which intent applies.

### Step 2. Load

Read **all** matching files in one batch (parallel reads). Keep them
in the active context for the rest of the session.

If multiple postmortems exist, read the 3 most recent + any whose
title matches the current incident's keyword.

### Step 3. Briefly summarize what you loaded

One short paragraph: which files / what they cover. Don't quote whole
documents back to the user — the goal is to signal readiness, not to
dump.

### Step 4. Stop

Hand off to the user (or to `/debug` / `/code-infra` for the next
step). Don't start exploring code or running commands here.

## Notes

- This skill **only** reads workspace-static knowledge. It does not
  query the live graph or external APIs.
- If `infrastructure.md` is missing, ask the user whether they want to
  start one. Don't auto-create — workspace structure is theirs to own.
- For scope outside the workspace (e.g., curiosity about another team
  area), suggest creating a separate workspace rather than polluting
  this one.
