# /code-infra — Infrastructure code implementation

Workspace-aware "I'm about to write Terraform / k8s manifests / a
CI config" preflight. Establishes target & context from workspace
docs *before* exploring the target repo.

## Procedure

### Step 1. Load workspace context

- `<workspace>/infrastructure.md` — topology, project / cluster names
- `<workspace>/universe/*.yaml` — service inventory, deploy config

Without these, ask the user for the necessary anchors before diving
in (which GCP project? which cluster? which namespace?).

### Step 2. Read the relevant slice

Map intent → workspace file:

| Intent | Workspace file(s) |
|--------|-------------------|
| Touch a specific service | `universe/services.yaml` (or per-service file) |
| GCP / DNS / domain change | `infrastructure.md` |
| New service onboarding | both |

Read just the relevant entries — don't dump entire inventory.

### Step 3. Then explore the target repo

Now and only now, look at the existing code in the target repo
(Terraform module, Helm chart, kustomize overlay, CI config).

Goal: find existing patterns to reuse. Search for:

- Modules already invoked for similar services
- Variable conventions (naming, tagging, env split)
- Existing tests / lint configs

### Step 4. Draft a plan

Before writing code, share a short plan:

- Files to add / change
- Modules / patterns reused
- Risks (state mutation, downtime, blast radius)

Wait for approval.

### Step 5. Implement

Apply edits. Keep commits scoped — one logical change per commit.

### Step 6. Validation

- Terraform: `terraform plan` (never `apply` without confirmation)
- k8s: `kubectl diff` or `kubectl apply --dry-run=client`
- Helm: `helm template` + diff against current

Show output, wait for explicit approval before any apply.

## Hard rules

- **NEVER run `terraform apply` / `kubectl apply` (without dry-run) /
  `helm install` without explicit user confirmation.** Ever.
- Reuse modules — copy-paste from another team is the bug magnet.
- If `infrastructure.md` doesn't cover the target domain, stop and
  ask. Don't guess GCP project IDs from repo string-grepping.

## Step 7. /save check

If implementing this revealed something durable — module conventions,
non-obvious constraints, gotchas — propose `/save` before ending:

> 이번 작업에서 ~ 알게 됐는데 `knowledge/<topic>.md`에 정리할까요?

Skip when the change was mechanical.

## Notes

- For *investigating* an incident (not coding a fix), use `/debug`.
- For loading context only (no work), use `/infra`.
- This skill stops short of merge — PR review happens via
  `/check-review` → `/apply-review`.
