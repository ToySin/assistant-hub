"""Layer 2 enrichment — extract concepts from Issue text via Claude.

Reads every Issue's title + body, asks Claude for a list of concepts
with confidence scores, and writes them into the graph as
`Issue -> mentions -> Concept` edges. The `mentions` edge already has
provenance / confidence / extracted_by fields in the schema; this
module is the pipeline that fills them.

Auth: reads ANTHROPIC_API_KEY from the workspace's .env (preferred)
or process environment.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from anthropic import Anthropic

from graph import builder
from library.sources.config import _load_dotenv
from library.workspace import get_workspace_path

MODEL = "claude-haiku-4-5-20251001"
EXTRACTOR_VERSION = f"library.enrichment-{MODEL}"

SYSTEM_PROMPT = """You extract key concepts from work-tracking issue bodies.

For each input, return a JSON array of objects:
  [{"name": "<concept>", "confidence": <0.0-1.0>}]

Concepts should be:
- Technical components / services / technologies (e.g., "Redis", "HPA", "SurrealDB")
- Domain concepts specific to the work (e.g., "auto-sync", "session continuity", "ETL pipeline")
- Specific tools / libraries / commands (e.g., "Anthropic SDK", "/briefing", "gh CLI")

NOT:
- Generic words ("issue", "TODO", "feature", "system")
- Bare letters / abbreviations without context
- Filler ("the", "a", "this")

Confidence rubric:
- 0.95+ for explicit verbatim mentions
- 0.7-0.9 for clearly inferred concepts
- below 0.7 only when the connection is ambiguous

Return ONLY the JSON array. No prose, no code fences. Empty array if nothing clear.
"""


@dataclass
class Stats:
    issues_processed: int = 0
    concepts_extracted: int = 0
    edges_created: int = 0


def enrich(workspace: str | None = None) -> Stats:
    """Run extraction over all Issues in the active workspace's graph."""
    _load_dotenv(get_workspace_path(workspace) / ".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to the workspace's .env "
            "(ANTHROPIC_API_KEY=sk-ant-...) or export it in your shell."
        )

    client = Anthropic(api_key=api_key)
    db = builder.connect(workspace)

    issues = db.query(
        "SELECT id, source, external_key, title, body FROM Issue;"
    )

    stats = Stats()
    for issue in issues:
        body = issue.get("body") or ""
        text = f"{issue['title']}\n\n{body}".strip()
        if not text:
            continue
        try:
            concepts = _extract_concepts(client, text)
        except Exception as exc:  # noqa: BLE001
            print(f"[enrichment] skip {issue['external_key']}: {exc}")
            continue
        stats.issues_processed += 1
        for concept in concepts:
            name = (concept.get("name") or "").strip()
            if not name:
                continue
            concept_id = builder.upsert_concept(db, name)
            builder.relate(
                db, issue["id"], "mentions", concept_id,
                confidence=float(concept.get("confidence", 0.7)),
                provenance="extracted",
                extracted_by=EXTRACTOR_VERSION,
            )
            stats.concepts_extracted += 1
            stats.edges_created += 1

    return stats


def _extract_concepts(client: Anthropic, text: str) -> list[dict]:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": text}],
    )
    content = resp.content[0].text.strip()
    # Tolerate occasional code-fence wrapping
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[: content.rfind("```")].rstrip()
    return json.loads(content)


def main() -> None:
    stats = enrich()
    print(f"[enrichment] {stats}")


if __name__ == "__main__":
    main()
