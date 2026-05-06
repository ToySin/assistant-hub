"""Per-workspace sync-state tracker (last-sync timestamps per source / scope).

State lives at `<workspace>/sync_state.json` (gitignored — regenerable,
machine-local). Read/write is per-scope so one source can track multiple
repos or projects independently.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from library.workspace import get_workspace_path

FILENAME = "sync_state.json"
DEFAULT_SCOPE = "_default"


def _path(workspace: str | None = None):
    return get_workspace_path(workspace) / FILENAME


def get(source: str, scope: str = DEFAULT_SCOPE,
        workspace: str | None = None) -> str | None:
    """Return ISO-8601 UTC timestamp of last successful sync, or None if
    we have no record (caller should treat that as 'do a full sync')."""
    p = _path(workspace)
    if not p.is_file():
        return None
    return json.loads(p.read_text()).get(source, {}).get(scope)


def set_(source: str, scope: str = DEFAULT_SCOPE,
         workspace: str | None = None, ts: str | None = None) -> str:
    """Persist `ts` (default: now) as last-sync for (source, scope)."""
    if ts is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p = _path(workspace)
    state = json.loads(p.read_text()) if p.is_file() else {}
    state.setdefault(source, {})[scope] = ts
    p.write_text(json.dumps(state, indent=2, sort_keys=True))
    return ts


def reset(workspace: str | None = None) -> None:
    p = _path(workspace)
    if p.is_file():
        p.unlink()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
