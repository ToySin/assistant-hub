"""Workspace path resolution.

Active workspace resolution order:
1. `ASSISTHUB_WORKSPACE` environment variable (per-shell override).
2. Pointer file at `~/.config/assisthub/active` (set by `assisthub use`).

Workspaces live under `ASSISTHUB_LOCATION` (default: `~/repositories`) as
directories named `assisthub-ws-<name>/`.
"""

from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ENV = "ASSISTHUB_WORKSPACE"
LOCATION_ENV = "ASSISTHUB_LOCATION"
WORKSPACE_PREFIX = "assisthub-ws-"
POINTER_PATH = Path.home() / ".config" / "assisthub" / "active"


class WorkspaceNotSetError(RuntimeError):
    """Raised when no active workspace is configured."""


class WorkspaceNotFoundError(RuntimeError):
    """Raised when the active workspace directory does not exist."""


def get_active_workspace() -> str:
    """Return the active workspace name. Env var wins so a shell can
    temporarily switch context without touching the pointer file."""
    name = os.environ.get(WORKSPACE_ENV, "").strip()
    if name:
        return name
    if POINTER_PATH.is_file():
        name = POINTER_PATH.read_text().strip()
        if name:
            return name
    raise WorkspaceNotSetError(
        f"No active workspace. Set one with `assisthub use <name>` or "
        f"`export {WORKSPACE_ENV}=<name>`."
    )


def get_workspaces_root() -> Path:
    """Return the directory that contains all workspace repos."""
    location = os.environ.get(LOCATION_ENV, "").strip()
    if location:
        return Path(location).expanduser()
    return Path.home() / "repositories"


def get_workspace_path(name: str | None = None) -> Path:
    """Return the path to a workspace repo. Defaults to the active workspace."""
    workspace_name = name if name is not None else get_active_workspace()
    path = get_workspaces_root() / f"{WORKSPACE_PREFIX}{workspace_name}"
    if not path.is_dir():
        raise WorkspaceNotFoundError(
            f"Workspace '{workspace_name}' not found at {path}. "
            f"Create it with `scripts/new-workspace.sh {workspace_name}`."
        )
    return path


def get_workspace_db_path(name: str | None = None) -> Path:
    """Return the path to the workspace's local DB file (created on first use)."""
    return get_workspace_path(name) / "db" / "graph.db"


def get_workspace_export_dir(name: str | None = None) -> Path:
    """Return the directory where DB exports are committed for sync."""
    return get_workspace_path(name) / "exports"
