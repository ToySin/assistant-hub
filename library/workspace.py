"""Workspace path resolution.

Active workspace is selected via the `ASSISTHUB_WORKSPACE` environment variable.
Workspaces live under `ASSISTHUB_LOCATION` (default: `~/repositories`) as
directories named `assisthub-ws-<name>/`.
"""

from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ENV = "ASSISTHUB_WORKSPACE"
LOCATION_ENV = "ASSISTHUB_LOCATION"
WORKSPACE_PREFIX = "assisthub-ws-"


class WorkspaceNotSetError(RuntimeError):
    """Raised when no active workspace is configured."""


class WorkspaceNotFoundError(RuntimeError):
    """Raised when the active workspace directory does not exist."""


def get_active_workspace() -> str:
    """Return the active workspace name from the environment."""
    name = os.environ.get(WORKSPACE_ENV, "").strip()
    if not name:
        raise WorkspaceNotSetError(
            f"{WORKSPACE_ENV} is not set. Export it to the workspace short name "
            f"(e.g. `export {WORKSPACE_ENV}=hub-improvement`)."
        )
    return name


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
