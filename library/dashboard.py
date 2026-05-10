"""Workspace dashboard bootstrap and helpers.

`dashboard.yaml` ships with every field empty (`focus: []`, `blockers:
[]`, etc.). That makes briefing/act look thin until the user fills it
in by hand. Most of the `projects:` list, though, is mechanical: it
mirrors the source projects already declared in `sources.yaml`.

This module's `bootstrap` reads `sources.yaml` + `dashboard.yaml`,
appends entries to `projects:` that aren't there yet, and leaves
everything else alone. Idempotent — re-running adds only newly-detected
sources and never overwrites a hand-edited entry.

CLI:
    python -m library.dashboard bootstrap        # add detected projects
    python -m library.dashboard bootstrap --dry  # show diff, write nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from library.workspace import get_workspace_path


def bootstrap(workspace: str | None = None, dry: bool = False) -> dict:
    """Add `projects:` entries from sources.yaml to dashboard.yaml.

    Returns a dict with `added` (list[dict] of new entries) and
    `existing` (count of pre-existing matching entries).
    """
    ws = get_workspace_path(workspace)
    sources_path = ws / "sources.yaml"
    dashboard_path = ws / "dashboard.yaml"

    sources = yaml.safe_load(sources_path.read_text()) or {}
    dashboard = yaml.safe_load(dashboard_path.read_text()) or {}

    existing_projects = dashboard.get("projects") or []
    existing_keys = {_project_key(p) for p in existing_projects if isinstance(p, dict)}

    detected = list(_detect_projects(sources.get("sources") or {}))
    added = [p for p in detected if _project_key(p) not in existing_keys]

    if not added:
        return {"added": [], "existing": len(existing_projects)}

    dashboard["projects"] = list(existing_projects) + added

    if not dry:
        dashboard_path.write_text(_dump(dashboard))

    return {"added": added, "existing": len(existing_projects)}


def _detect_projects(sources: dict) -> list[dict]:
    """Pull project-like rows out of sources.yaml.

    Each entry shape:
        {key, name, source}

    Where `source` is the source adapter name (jira / github / ...) and
    `key` is the unique identifier inside that source.
    """
    out: list[dict] = []

    jira = sources.get("jira") or {}
    if jira.get("enabled"):
        for k in jira.get("project_keys") or []:
            out.append({"key": k, "name": k, "source": "jira"})

    github = sources.get("github") or {}
    if github.get("enabled"):
        for repo in github.get("repos") or []:
            out.append({"key": repo, "name": repo, "source": "github"})

    gh_issues = sources.get("github_issues") or {}
    if gh_issues.get("enabled"):
        for repo in gh_issues.get("repos") or []:
            out.append({"key": repo, "name": repo, "source": "github_issues"})

    confluence = sources.get("confluence") or {}
    if confluence.get("enabled"):
        for sp in confluence.get("spaces") or []:
            out.append({"key": sp, "name": sp, "source": "confluence"})

    notion = sources.get("notion") or {}
    if notion.get("enabled"):
        for db_id in notion.get("database_ids") or []:
            out.append({"key": db_id, "name": db_id, "source": "notion"})

    return out


def _project_key(p: dict) -> tuple[str, str]:
    """Composite (source, key) — same `key` across sources is allowed
    (e.g. Jira 'BA' and Confluence 'BEARAPI' are distinct entries)."""
    return (p.get("source") or "", p.get("key") or "")


def _dump(dashboard: dict) -> str:
    """yaml.safe_dump with the project lists rendered legibly. Not a full
    AST round-trip — this module is the canonical writer for projects:,
    so re-emitting from parsed YAML is fine."""
    # Force a stable key order for the top-level fields.
    canonical = {}
    for k in ("workspace", "focus", "blockers", "action_items", "projects"):
        if k in dashboard:
            canonical[k] = dashboard[k]
    for k, v in dashboard.items():
        if k not in canonical:
            canonical[k] = v
    return yaml.safe_dump(
        canonical, sort_keys=False, allow_unicode=True, width=100,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Workspace dashboard helpers.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    boot = sub.add_parser("bootstrap", help="Add detected projects to dashboard.yaml.")
    boot.add_argument("--workspace", help="Override active workspace.")
    boot.add_argument("--dry", action="store_true", help="Show diff, write nothing.")
    args = parser.parse_args()

    if args.cmd == "bootstrap":
        result = bootstrap(args.workspace, dry=args.dry)
        if not result["added"]:
            print(f"No new projects detected ({result['existing']} already in dashboard).")
            return
        print(f"Added {len(result['added'])} project(s):")
        for p in result["added"]:
            print(f"  - [{p['source']}] {p['key']}")
        if args.dry:
            print("(--dry — nothing written)")
        sys.exit(0)


if __name__ == "__main__":
    main()
