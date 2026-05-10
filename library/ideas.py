"""Idea capture and promotion.

Ideas are markdown files under `<workspace>/notes/ideas/` with a small
YAML frontmatter (status, captured_at, effort, tags, related,
promoted_to). They ride the existing `markdown_dirs` Note pipeline —
capture writes the file, refresh the graph, and the file shows up as a
Note. Promotion creates a GitHub issue, updates the frontmatter, and
links the new Issue back to the originating Note via `extracted_from`.

CLI:
    python -m library.ideas capture "<freeform text>"
    python -m library.ideas promote <slug> --repo <owner/name>
    python -m library.ideas list
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from library.workspace import get_workspace_path

IDEAS_SUBDIR = "notes/ideas"
SLUG_RE = re.compile(r"[^a-z0-9]+")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


# -----------------------------------------------------------------------------
# Filesystem helpers
# -----------------------------------------------------------------------------

def ideas_dir(workspace: str | None = None) -> Path:
    return get_workspace_path(workspace) / IDEAS_SUBDIR


def _slug(text: str, max_len: int = 48) -> str:
    s = SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return (s[:max_len] or "idea").rstrip("-")


def _today_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    front = yaml.safe_load(m.group(1)) or {}
    return front, m.group(2)


def _write(path: Path, front: dict, body: str) -> None:
    front_yaml = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{front_yaml}\n---\n{body}")


# -----------------------------------------------------------------------------
# Capture
# -----------------------------------------------------------------------------

def capture(
    text: str,
    *,
    title: str | None = None,
    slug: str | None = None,
    workspace: str | None = None,
) -> Path:
    """Write a new idea markdown file. Returns its path.

    `slug` lets the caller supply the filename component independently
    of `title`. Useful for non-Latin titles (e.g. Korean) where the
    auto-derived slug would collapse to "idea".
    """
    text = text.strip()
    if not text:
        raise ValueError("capture: empty text")

    if title is None:
        title = text.splitlines()[0].strip().rstrip(".:!?")
        if len(title) > 80:
            title = title[:77] + "..."

    file_slug = _slug(slug) if slug else _slug(title)

    out_dir = ideas_dir(workspace)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_today_prefix()}-{file_slug}.md"

    n = 1
    while path.exists():
        n += 1
        path = out_dir / f"{_today_prefix()}-{file_slug}-{n}.md"

    front = {
        "title": title,
        "status": "captured",
        "captured_at": _now_iso(),
        "effort": None,
        "tags": [],
        "related": [],
        "promoted_to": "",
    }
    body = f"## What\n{text}\n\n## Why\n_(refine to fill in)_\n\n## Notes\n"
    _write(path, front, body)
    return path


# -----------------------------------------------------------------------------
# Promote
# -----------------------------------------------------------------------------

def promote(slug_or_path: str, *, repo: str, workspace: str | None = None) -> str:
    """Open a GitHub issue from an idea, mark the file promoted, and link
    the resulting Issue back to the originating Note. Returns the issue URL."""
    path = _resolve_idea(slug_or_path, workspace)
    front, body = _read(path)
    if front.get("status") == "promoted" and front.get("promoted_to"):
        # Already promoted — make sure the graph link exists. Idempotent
        # so a partial first run can be completed by re-invoking promote.
        _refresh_graph_and_link(path, front["promoted_to"], workspace)
        return front["promoted_to"]

    title = front.get("title") or path.stem
    issue_body = _build_issue_body(front, body)
    url = _gh_create_issue(repo, title, issue_body)

    front["status"] = "promoted"
    front["promoted_to"] = url
    front["promoted_at"] = _now_iso()
    _write(path, front, body)

    _refresh_graph_and_link(path, url, workspace)
    return url


def _build_issue_body(front: dict, body: str) -> str:
    lines = [body.rstrip(), ""]
    extras = []
    if front.get("effort"):
        extras.append(f"**Effort:** {front['effort']}")
    if front.get("tags"):
        extras.append(f"**Tags:** {', '.join(front['tags'])}")
    if front.get("related"):
        extras.append(f"**Related:** {', '.join(front['related'])}")
    if extras:
        lines.extend(["---", *extras])
    return "\n".join(lines)


def _gh_create_issue(repo: str, title: str, body: str) -> str:
    res = subprocess.run(
        ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
        capture_output=True, text=True, check=True,
    )
    url = res.stdout.strip().splitlines()[-1]
    if not url.startswith("http"):
        raise RuntimeError(f"gh did not return an issue URL: {res.stdout!r}")
    return url


def _refresh_graph_and_link(idea_path: Path, issue_url: str, workspace: str | None) -> None:
    """Re-run the two relevant ETLs so the graph reflects the new state,
    then add the extracted_from edge from the new Issue to the Note."""
    from graph import builder
    from library.sources import config as source_config
    from library.sources import github_issues as gh_issues_etl
    from library.sources import markdown_dirs as md_etl

    enabled = {s.name: s for s in source_config.load(workspace)}
    db = builder.connect(workspace)
    builder.apply_schema(db)

    if "markdown_dirs" in enabled:
        s = enabled["markdown_dirs"]
        md_etl.sync(db, s.settings, s.auth)
    if "github_issues" in enabled:
        s = enabled["github_issues"]
        gh_issues_etl.sync(db, s.settings, s.auth)

    issue_external = _issue_external_from_url(issue_url)
    if not issue_external:
        return
    issue_id = builder.ensure_issue(db, source="github", external_key=issue_external)
    note_rows = db.query(
        "SELECT id FROM Note WHERE source = 'markdown_dirs' AND path = $path;",
        {"path": str(idea_path)},
    )
    note_id = (
        note_rows[0]["id"]
        if note_rows and isinstance(note_rows[0], dict)
        else None
    )
    if note_id is None:
        return

    # Idempotent edge create — RELATE always inserts a new row, so check first.
    existing = db.query(
        "SELECT id FROM extracted_from WHERE in = $issue AND out = $note;",
        {"issue": issue_id, "note": note_id},
    )
    if existing:
        return
    builder.relate(
        db, issue_id, "extracted_from", note_id,
        confidence=1.0,
        extracted_by="library.ideas.promote",
    )


def _issue_external_from_url(url: str) -> str | None:
    # https://github.com/<owner>/<repo>/issues/<n>
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/issues/(\d+)", url)
    if not m:
        return None
    return f"{m.group(1)}#{m.group(2)}"


# -----------------------------------------------------------------------------
# List
# -----------------------------------------------------------------------------

def list_ideas(workspace: str | None = None) -> list[dict]:
    out: list[dict] = []
    d = ideas_dir(workspace)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        front, _ = _read(p)
        out.append({
            "slug": p.stem,
            "path": str(p),
            "title": front.get("title") or p.stem,
            "status": front.get("status") or "?",
            "promoted_to": front.get("promoted_to") or "",
        })
    return out


def _resolve_idea(slug_or_path: str, workspace: str | None) -> Path:
    p = Path(slug_or_path)
    if p.is_file():
        return p
    d = ideas_dir(workspace)
    candidate = d / f"{slug_or_path}.md"
    if candidate.is_file():
        return candidate
    matches = list(d.glob(f"*{slug_or_path}*.md"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"no idea file matches '{slug_or_path}' under {d}")
    raise ValueError(f"ambiguous slug '{slug_or_path}': {[m.name for m in matches]}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Capture / promote workspace ideas.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="Write a new idea markdown file.")
    cap.add_argument("text", help="Freeform idea text.")
    cap.add_argument("--title", help="Optional explicit title.")
    cap.add_argument("--slug", help="Optional explicit filename slug (useful for non-Latin titles).")

    prm = sub.add_parser("promote", help="Open a GitHub issue from an idea.")
    prm.add_argument("slug", help="Idea slug, filename, or absolute path.")
    prm.add_argument("--repo", required=True, help="owner/repo for the GitHub issue.")

    sub.add_parser("list", help="List captured ideas.")

    args = parser.parse_args()

    if args.cmd == "capture":
        path = capture(args.text, title=args.title, slug=args.slug)
        print(path)
    elif args.cmd == "promote":
        url = promote(args.slug, repo=args.repo)
        print(url)
    elif args.cmd == "list":
        for entry in list_ideas():
            print(json.dumps(entry, ensure_ascii=False))
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
