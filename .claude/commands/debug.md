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

## Step 5. Post-investigation — propose /save immediately

When the incident is resolved, **don't wait for the user**. Propose
`/save` right then:

> 해결됐네요. 정리할까요?
> 1. `runbooks/case-studies.md`에 case/symptom/root cause/resolution 추가
> 2. (영향 큰 인시던트면) `runbooks/postmortems/<date>-<slug>.md` 작성
> 3. 첫 해결 패턴이면 `semi-auto` runbook 자동 생성 (`library/runbooks.py` 사이클)
>
> 어디까지 할까요?

Don't auto-commit; the user picks.

If the user says "skip" / "나중에", note it but proceed — `/save` at
session end will surface the same options as a fallback.

## Notes

- This skill is read-heavy and ask-once. Don't churn through
  hypotheses without checking against existing knowledge first.
- "It's not in any of our docs" is itself important data — surface it
  so the user knows the gap.
