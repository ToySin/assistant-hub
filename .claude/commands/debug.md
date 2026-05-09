# /debug — Incident investigation

Workspace-aware investigation flow. Loads infra context first
(`/infra` style), references prior incidents, then traces.

## Procedure

### Step 1. Load context

Read whichever workspace files exist (use `/infra` if you want a more
explicit preload step first):

- `<workspace>/infrastructure.md`
- `<workspace>/runbooks/case-studies.md`
- `<workspace>/runbooks/postmortems/*.md`

If any are missing, note it and proceed with what's available.

### Step 2. Match prior incidents

Skim postmortems and case studies for the current symptom keyword
(error code, service name, behavior). If a match is found, **lead
with the prior root cause and recovery method** — most recurrences
match a known pattern.

If a workspace runbook matches the event signature, mention it
explicitly:

> 비슷한 패턴: `runbooks/<name>.md` (root cause: ...). 이것부터 확인할까요?

### Step 3. Trace

Based on the loaded mappings, run the next diagnostic step. Examples:

- 502 on a service → check its pod state (`kubectl get pods`) +
  recent autoscaler events
- API error → check service logs + upstream dep health
- Auth issue → check IAM bindings + service account state

Use only mappings + checklists from the loaded files. **Do NOT explore
repo code (Terraform, manifests) further** at this stage — that's
`/code-infra`.

If the affected service / domain isn't in `infrastructure.md`,
confirm with the user before guessing.

### Step 4. Recovery

Recovery actions (`kubectl apply`, scale, restart, rollback) **always
require explicit user confirmation**. Show the proposed command + its
expected effect, wait for `y`.

Never run irreversible actions silently in auto mode.

## Step 5. Post-investigation

When the incident is resolved:

1. Add an entry to `<workspace>/runbooks/case-studies.md` if this
   pattern is new — case / symptom / root cause / diagnostic queries
   / resolution. (`/save` will propose this on session end if you
   skip it now.)
2. If the incident warrants a full postmortem (significant outage,
   user-facing impact), draft `<workspace>/runbooks/postmortems/
   YYYY-MM-DD-<slug>.md`. `/save` proposes this too.
3. Consider a new runbook entry — if this is the first time you've
   resolved this pattern, the resolution steps become a `semi-auto`
   runbook on the next encounter (see `library/runbooks.py` lifecycle).

## Notes

- This skill is read-heavy and ask-once. Don't churn through
  hypotheses without checking against existing knowledge first.
- "It's not in any of our docs" is itself important data — surface it
  so the user knows the gap.
