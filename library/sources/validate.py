"""Per-source connectivity / auth probe.

Run after `/configure-sources` (or any time creds change) to confirm
each enabled source can actually be reached *before* the first big
ETL. The point is to fail fast with a specific, actionable error
instead of letting the user discover the problem 30 minutes into
their first sync.

Each probe is a minimal call:

  jira          GET /rest/api/3/myself
  confluence    GET /rest/api/space/<first-key>
  github        gh auth status + gh api repos/<first-repo>
  github_issues same as github
  gdrive_gemini Drive API list with limit=1
  markdown_dirs each path is a directory

Sources without a probe pass with "skipped — no probe defined" so the
report shape stays uniform.

CLI:
    python -m library.sources.validate                  # all enabled
    python -m library.sources.validate --source jira    # one
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from library.sources import config as source_config


@dataclass
class ProbeResult:
    source: str
    ok: bool
    message: str


# ---------------------------------------------------------------------------
# Per-source probes
# ---------------------------------------------------------------------------

def _probe_jira(settings: dict, auth: str | None) -> ProbeResult:
    base_url = (settings.get("base_url") or "").rstrip("/")
    if not base_url:
        return ProbeResult("jira", False, "base_url is empty in sources.yaml")
    email = os.environ.get("JIRA_EMAIL")
    if not email:
        return ProbeResult("jira", False, "JIRA_EMAIL not set in .env")
    if not auth:
        return ProbeResult("jira", False, "JIRA_TOKEN not set in .env")
    r = requests.get(
        f"{base_url}/rest/api/3/myself",
        auth=(email, auth),
        timeout=15,
    )
    if r.status_code == 401:
        return ProbeResult(
            "jira", False,
            "401 Unauthorized — check JIRA_EMAIL / JIRA_TOKEN. "
            "Token at https://id.atlassian.com/manage-profile/security/api-tokens",
        )
    if r.status_code != 200:
        return ProbeResult("jira", False, f"HTTP {r.status_code}: {r.text[:120]}")
    me = r.json()
    return ProbeResult("jira", True, f"auth OK as {me.get('displayName', email)}")


def _probe_confluence(settings: dict, auth: str | None) -> ProbeResult:
    base_url = (settings.get("base_url") or "").rstrip("/")
    if not base_url:
        return ProbeResult("confluence", False, "base_url is empty")
    email = os.environ.get("CONFLUENCE_EMAIL") or os.environ.get("JIRA_EMAIL")
    if not email:
        return ProbeResult(
            "confluence", False,
            "neither CONFLUENCE_EMAIL nor JIRA_EMAIL is set in .env",
        )
    if not auth:
        return ProbeResult("confluence", False, "CONFLUENCE_TOKEN not set in .env")
    spaces = settings.get("spaces") or []
    if not spaces:
        # Auth-only check
        r = requests.get(
            f"{base_url}/rest/api/space",
            params={"limit": 1},
            auth=(email, auth),
            timeout=15,
        )
        if r.status_code != 200:
            return ProbeResult("confluence", False, f"HTTP {r.status_code}: {r.text[:120]}")
        return ProbeResult("confluence", True, "auth OK (no spaces configured)")
    # Verify access to first space
    first = spaces[0]
    r = requests.get(
        f"{base_url}/rest/api/space/{first}",
        auth=(email, auth),
        timeout=15,
    )
    if r.status_code == 404:
        return ProbeResult(
            "confluence", False,
            f"space '{first}' not found — check the space key, "
            "and confirm your account has access",
        )
    if r.status_code != 200:
        return ProbeResult("confluence", False, f"HTTP {r.status_code}: {r.text[:120]}")
    return ProbeResult(
        "confluence", True,
        f"auth OK + space '{first}' reachable ({len(spaces)} space(s) configured)",
    )


def _probe_github_like(settings: dict, label: str) -> ProbeResult:
    if not shutil.which("gh"):
        return ProbeResult(
            label, False, "`gh` CLI not on PATH — install via https://cli.github.com/",
        )
    auth = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True,
    )
    if auth.returncode != 0:
        return ProbeResult(
            label, False,
            "gh CLI not authenticated — run `gh auth login`",
        )
    repos = settings.get("repos") or []
    if not repos:
        return ProbeResult(label, True, "gh CLI auth OK (no repos configured)")
    first = repos[0]
    res = subprocess.run(
        ["gh", "api", f"repos/{first}", "--jq", ".name"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return ProbeResult(
            label, False,
            f"repo '{first}' not accessible — verify the slug and your gh "
            f"account has access. stderr: {res.stderr.strip()[:120]}",
        )
    return ProbeResult(
        label, True,
        f"gh OK + repo '{first}' reachable ({len(repos)} repo(s) configured)",
    )


def _probe_github(settings: dict, auth: str | None) -> ProbeResult:
    return _probe_github_like(settings, "github")


def _probe_github_issues(settings: dict, auth: str | None) -> ProbeResult:
    return _probe_github_like(settings, "github_issues")


def _probe_gdrive_like(settings: dict, auth: str | None, label: str) -> ProbeResult:
    """Shared Drive-API probe — gdrive_gemini and gdrive_docs use the
    same gcloud ADC path, so probe logic is identical."""
    if not shutil.which("gcloud"):
        return ProbeResult(label, False, "`gcloud` not on PATH — install Google Cloud SDK")
    tok = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True,
    )
    if tok.returncode != 0:
        return ProbeResult(
            label, False,
            "no Application Default Credentials — run "
            "`gcloud auth application-default login --scopes=openid,"
            "https://www.googleapis.com/auth/drive.readonly,"
            "https://www.googleapis.com/auth/cloud-platform`",
        )
    proj = subprocess.run(
        ["gcloud", "config", "get-value", "project"],
        capture_output=True, text=True,
    )
    headers = {
        "Authorization": f"Bearer {tok.stdout.strip()}",
        "x-goog-user-project": proj.stdout.strip(),
    }
    r = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"pageSize": 1, "corpora": "user"},
        headers=headers,
        timeout=15,
    )
    if r.status_code == 403:
        return ProbeResult(
            label, False,
            "Drive API returned 403. Either Drive API isn't enabled on the "
            "active gcloud project (enable at "
            "console.cloud.google.com/apis/library/drive.googleapis.com) "
            "or ADC token is missing drive.readonly scope (re-login with "
            "the scopes flag above).",
        )
    if r.status_code != 200:
        return ProbeResult(label, False, f"HTTP {r.status_code}: {r.text[:120]}")
    return ProbeResult(label, True, "ADC + Drive API OK")


def _probe_gdrive_gemini(settings: dict, auth: str | None) -> ProbeResult:
    return _probe_gdrive_like(settings, auth, "gdrive_gemini")


def _probe_gdrive_docs(settings: dict, auth: str | None) -> ProbeResult:
    return _probe_gdrive_like(settings, auth, "gdrive_docs")


def _probe_markdown_dirs(settings: dict, auth: str | None) -> ProbeResult:
    paths = settings.get("paths") or []
    if not paths:
        return ProbeResult("markdown_dirs", False, "paths is empty")
    missing = [p for p in paths if not Path(p).expanduser().is_dir()]
    if missing:
        return ProbeResult(
            "markdown_dirs", False,
            f"path(s) not found: {missing}",
        )
    return ProbeResult(
        "markdown_dirs", True, f"{len(paths)} path(s) all exist",
    )


PROBES = {
    "jira": _probe_jira,
    "confluence": _probe_confluence,
    "github": _probe_github,
    "github_issues": _probe_github_issues,
    "gdrive_docs": _probe_gdrive_docs,
    "gdrive_gemini": _probe_gdrive_gemini,
    "markdown_dirs": _probe_markdown_dirs,
}


# ---------------------------------------------------------------------------
# Orchestrator + CLI
# ---------------------------------------------------------------------------

def validate(workspace: str | None = None,
             source: str | None = None) -> list[ProbeResult]:
    sources = source_config.load(workspace)
    if source:
        sources = [s for s in sources if s.name == source]
    if not sources:
        return []

    results: list[ProbeResult] = []
    for s in sources:
        fn = PROBES.get(s.name)
        if fn is None:
            results.append(ProbeResult(
                s.name, True, "no probe defined — skipped",
            ))
            continue
        try:
            results.append(fn(s.settings, s.auth))
        except Exception as exc:  # noqa: BLE001
            results.append(ProbeResult(s.name, False, f"probe failed: {exc}"))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-probe each enabled source for auth + connectivity."
    )
    parser.add_argument("--source", help="Probe only this source.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    args = parser.parse_args()

    results = validate(source=args.source)
    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2, ensure_ascii=False))
        sys.exit(0 if all(r.ok for r in results) else 1)

    print(f"Probed {len(results)} source(s):\n")
    for r in results:
        mark = "OK " if r.ok else "FAIL"
        print(f"  [{mark}] {r.source}: {r.message}")
    failures = [r for r in results if not r.ok]
    if failures:
        print(f"\n{len(failures)} failure(s). Fix above before running ETL.")
        sys.exit(1)
    print("\nAll probes passed. ETL ready to run.")


if __name__ == "__main__":
    main()
