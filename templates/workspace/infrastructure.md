# Infrastructure — {{WORKSPACE_NAME}}

> **Skeleton.** Fill this in with topology / project / cluster / domain
> mappings as you onboard the workspace. `/infra`, `/debug`, and
> `/code-infra` skills load this file to establish target & context
> *before* exploring the target repo. The richer this file gets, the
> more useful those skills become.

## Cloud / hosting

- **Provider(s)**: e.g., GCP, AWS, internal
- **Project / account IDs**: list, with environment label (prod / dev / staging)
- **Regions**: primary / DR

## Clusters / runtimes

| Cluster | Project | Region | Purpose |
|---------|---------|--------|---------|
| _e.g. `prod-us-east`_ | _project-id_ | _us-east1_ | _user-facing services_ |

## Domains / DNS

- Primary: e.g., `app.example.com → ingress in <cluster>`
- Internal: e.g., `internal.example.com → ...`
- Cert / TLS notes:

## Services (high-level)

| Service | Repo | Cluster | Owners | Notes |
|---------|------|---------|--------|-------|
| | | | | |

For full service inventory (replicas, HPA, deploy config) keep a
separate `universe/services.yaml` if it gets long.

## Common diagnostics

- Pod state: `kubectl get pods -n <ns>`
- Recent autoscaler events: `gcloud logging read 'resource.type="k8s_cluster" AND ...'`
- Service health endpoint pattern: `https://<svc>/healthz`

Add real commands as you discover them — `/save` proposes adding here
when you resolve an incident with a non-obvious diagnostic.

## Constraints / gotchas

- Replica >= 2 + PodDisruptionBudget required for prod (see case-studies)
- ...
