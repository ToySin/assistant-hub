"""Load and resolve a workspace's sources.yaml.

Returns only enabled source configs, with the `auth_env` field replaced
by the actual secret pulled from the workspace's .env (loaded into
process env). Callers see plain `auth` strings, never env-var names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from library.workspace import get_workspace_path


@dataclass
class SourceConfig:
    name: str          # e.g. "jira", "github"
    settings: dict     # remaining fields after auth resolution
    auth: str | None   # resolved secret, None if source has no auth_env


def load(workspace: str | None = None) -> list[SourceConfig]:
    """Return enabled sources from the workspace's sources.yaml.

    Reads the workspace's .env into the current process so `auth_env`
    references resolve. Sources missing their auth secret are skipped
    with a warning printed to stderr.
    """
    ws_path = get_workspace_path(workspace)
    _load_dotenv(ws_path / ".env")

    raw = yaml.safe_load((ws_path / "sources.yaml").read_text()) or {}
    sources_block = raw.get("sources") or {}

    enabled: list[SourceConfig] = []
    for name, settings in sources_block.items():
        if not isinstance(settings, dict) or not settings.get("enabled"):
            continue
        auth = None
        env_var = settings.get("auth_env")
        if env_var:
            auth = os.environ.get(env_var)
            if not auth:
                print(f"[sources] skipping '{name}': env var {env_var} not set")
                continue
        enabled.append(SourceConfig(
            name=name,
            settings={k: v for k, v in settings.items() if k not in ("enabled", "auth_env")},
            auth=auth,
        ))
    return enabled


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (KEY=VALUE per line, # comments, ignores blanks)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)
