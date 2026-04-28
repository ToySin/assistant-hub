# {{WORKSPACE_NAME}}

assistant-hub workspace.

This repo is a sync target — it stores knowledge, dashboard state, and DB exports
for the `{{WORKSPACE_NAME}}` workspace. Direct manual edits are uncommon; most
content is updated by assistant-hub skills running in this workspace context.

## Layout

| Path | Purpose |
|------|---------|
| `dashboard.yaml` | Focus, blockers, action items |
| `sources.yaml` | Data source definitions for this workspace |
| `projects/` | Per-project trackers |
| `knowledge/` | Workspace-specific domain knowledge (markdown) |
| `runbooks/` | Operational runbooks |
| `exports/` | DB exports (created on sync — Neo4j Cypher, SQLite dumps) |

## Activation

```bash
export ASSISTHUB_WORKSPACE={{WORKSPACE_NAME}}
```

Or use the assistant-hub workspace switcher (TBD).
