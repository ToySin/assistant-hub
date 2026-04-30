"""Regex extractors for cross-references in free text.

Used by ETL to spot Jira keys and PR refs inside PR bodies, issue
descriptions, commit messages, etc., so the graph can record implicit
links that the source APIs don't expose directly.
"""

from __future__ import annotations

import re

# Jira issue key: PROJECT-123 (project must start with a letter, then
# letters/digits, then -<number>). Word-boundary anchored.
_JIRA_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

# GitHub PR shorthand: #123 or owner/repo#123
_PR_HASH_RE = re.compile(r"(?:([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+))?#(\d+)\b")

# GitHub PR URL
_PR_URL_RE = re.compile(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)")


def extract_jira_keys(text: str) -> list[str]:
    if not text:
        return []
    seen: dict[str, None] = {}
    for key in _JIRA_RE.findall(text):
        seen.setdefault(key, None)
    return list(seen)


def extract_pr_refs(text: str, default_repo: str = "") -> list[str]:
    """Return PR identifiers as 'owner/repo#number'. Skips bare '#N' refs
    when no `default_repo` is provided so we don't fabricate ambiguous IDs."""
    if not text:
        return []
    refs: dict[str, None] = {}
    for repo, num in _PR_HASH_RE.findall(text):
        repo = repo or default_repo
        if not repo:
            continue
        refs.setdefault(f"{repo}#{num}", None)
    for repo, num in _PR_URL_RE.findall(text):
        refs.setdefault(f"{repo}#{num}", None)
    return list(refs)
