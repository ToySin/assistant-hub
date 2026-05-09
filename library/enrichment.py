"""Layer 2 enrichment — distill structured signal out of free text via an LLM.

Two extraction modes share the same module:

1. **Concept extraction from Issues.** For each existing Issue, ask the
   LLM for the technical/domain concepts referenced in title+body and
   write them as `Issue -> mentions -> Concept` edges with provenance.

2. **Action item + concept extraction from Notes.** For each Note, ask
   the LLM for (a) the same kinds of concepts, plus (b) explicit action
   items that the note's author has written down. Each action item
   becomes a synthesized Issue (`source='note'`) linked back to the
   originating Note via an `extracted_from` edge. From this point on the
   action item is a first-class Issue and is picked up by /briefing,
   /act, /search etc. without further work.

Provider/model is selected by the env vars in `library.llm` — defaults
to Anthropic + ANTHROPIC_API_KEY, but can be pointed at OpenAI, a local
Ollama, or any other OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

from graph import builder
from library.llm import LLMClient, get_client
from library.sources.config import _load_dotenv
from library.workspace import get_workspace_path


CONCEPT_RULES = """Concepts are:
- Technical components / services / technologies (e.g. "Redis", "HPA", "SurrealDB")
- Domain concepts specific to the work (e.g. "auto-sync", "session continuity")
- Specific tools / libraries / commands (e.g. "Anthropic SDK", "/briefing", "gh CLI")

NOT:
- Generic words ("issue", "TODO", "feature", "system")
- Bare letters / abbreviations without context
- Filler ("the", "a", "this")

Confidence rubric:
- 0.95+ for explicit verbatim mentions
- 0.7-0.9 for clearly inferred concepts
- below 0.7 only when the connection is ambiguous"""


ISSUE_SYSTEM_PROMPT = f"""You extract key concepts from work-tracking issue bodies.

Return a JSON array:
  [{{"name": "<concept>", "confidence": <0.0-1.0>}}]

{CONCEPT_RULES}

Return ONLY the JSON array. No prose, no code fences. Empty array if nothing clear.
"""


NOTE_SYSTEM_PROMPT = f"""You extract structured signal from a personal note.

Return a JSON object:
{{
  "concepts": [{{"name": "<concept>", "confidence": <0.0-1.0>}}],
  "action_items": [
    {{
      "title": "<concise imperative phrase, max 80 chars>",
      "status": "open" | "done",
      "confidence": <0.0-1.0>
    }}
  ]
}}

Concept rules:
{CONCEPT_RULES}

Action item rules — only items the author wrote *as an action they need to
take*. Strong signals: explicit "TODO:", checkbox lines (`- [ ]`, `- [x]`),
imperative phrases ("ask Bob about ...", "fix Y by Friday", "follow up on Z").
Mark `status: "done"` for already-completed items (e.g. `- [x]`).

NOT action items:
- Vague intentions or musings ("I should think about ...")
- Observations or notes-to-self that aren't asks
- Items already completed and clearly archived (unless an explicit `- [x]`)

If the note has no clear action items, return an empty list. Same for concepts.

Return ONLY the JSON object. No prose, no code fences.
"""


@dataclass
class Stats:
    issues_processed: int = 0
    notes_processed: int = 0
    concepts_extracted: int = 0
    action_items_extracted: int = 0
    edges_created: int = 0
    stale_marked: int = 0
    errors: list[str] = field(default_factory=list)


def list_targets(workspace: str | None = None, new_only: bool = True) -> dict:
    """Collect Issues and Notes that need enrichment, as a JSON-friendly dict.

    Backs the `/enrich` skill, where Claude Code itself plays the role of
    the LLM and `enrichment.py` doesn't need an API key. `new_only`
    (default) skips Issues already covered by a `mentions` edge and Notes
    that already have any `extracted_from` edge — pass `new_only=False`
    to re-extract over everything.
    """
    db = builder.connect(workspace)

    issues_raw = db.query(
        "SELECT id, source, external_key, title, body FROM Issue "
        "WHERE source != 'note';"
    ) or []
    notes_raw = db.query(
        "SELECT id, source, path, title, body FROM Note;"
    ) or []

    if new_only:
        mentions = db.query("SELECT in FROM mentions;") or []
        already_mentioned = {str(row["in"]) for row in mentions if row.get("in")}
        issues_raw = [i for i in issues_raw
                      if str(i.get("id")) not in already_mentioned]

        extracted = db.query("SELECT out FROM extracted_from;") or []
        already_extracted = {str(row["out"]) for row in extracted if row.get("out")}
        notes_raw = [n for n in notes_raw
                     if str(n.get("id")) not in already_extracted]

    return {
        "issues": [
            {
                "source": i.get("source"),
                "external_key": i.get("external_key"),
                "title": i.get("title") or "",
                "body": i.get("body") or "",
            }
            for i in issues_raw
        ],
        "notes": [
            {
                "source": n.get("source"),
                "path": n.get("path"),
                "title": n.get("title") or "",
                "body": n.get("body") or "",
            }
            for n in notes_raw
        ],
    }


def apply_results(
    payload: dict,
    workspace: str | None = None,
    extracted_by: str = "claude-code-skill",
    prune_stale: bool = False,
) -> Stats:
    """Write pre-computed enrichment results to the graph.

    Mirrors `enrich()` but skips the LLM call — concepts and action items
    arrive in `payload`, produced upstream (typically by the `/enrich`
    skill running inside a Claude Code session). Items are matched to
    existing graph nodes by (source, external_key) for Issues and
    (source, path) for Notes; missing nodes are reported in `errors`
    rather than auto-created, since `targets` is the canonical source of
    truth for what exists.
    """
    _load_dotenv(get_workspace_path(workspace) / ".env")
    db = builder.connect(workspace)
    stats = Stats()

    for issue_payload in payload.get("issues") or []:
        source = issue_payload.get("source")
        external_key = issue_payload.get("external_key")
        if not (source and external_key):
            continue
        issue_id = builder.ensure_issue(db, source, external_key)
        _attach_concepts(db, issue_id, issue_payload.get("concepts") or [],
                         extracted_by, stats)
        stats.issues_processed += 1

    for note_payload in payload.get("notes") or []:
        source = note_payload.get("source")
        path = note_payload.get("path")
        if not (source and path):
            continue
        thing_id = builder._slugify(f"{source}_{path}")  # noqa: SLF001
        existing = db.query(
            "SELECT id FROM type::thing('Note', $thing_id);",
            {"thing_id": thing_id},
        )
        note_id = builder._maybe_id(existing)  # noqa: SLF001
        if note_id is None:
            stats.errors.append(f"note not found: {source}:{path}")
            continue

        new_keys: set[str] = set()
        for item in note_payload.get("action_items") or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            confidence = float(item.get("confidence", 0.7))
            status = (item.get("status") or "open").strip().lower()
            if status not in ("open", "done"):
                status = "open"
            external_key = _action_item_key(path, title)
            new_keys.add(external_key)
            issue_id = builder.upsert_issue(
                db, source="note", external_key=external_key,
                title=title, status=status, body=None,
            )
            builder.relate(
                db, issue_id, "extracted_from", note_id,
                confidence=confidence, extracted_by=extracted_by,
            )
            _attach_concepts(db, issue_id, note_payload.get("concepts") or [],
                             extracted_by, stats)
            stats.action_items_extracted += 1
            stats.edges_created += 1

        if prune_stale:
            stats.stale_marked += _mark_stale(db, note_id, new_keys)
        stats.notes_processed += 1

    return stats


def enrich(workspace: str | None = None,
           prune_stale: bool = False) -> Stats:
    """Run extraction over Issues and Notes in the active workspace's graph.

    `prune_stale=True`: after re-extracting from a Note, any Issue
    previously linked to that Note via extracted_from but missing
    from the new payload is marked `status = 'stale'`. Useful when a
    user removes / completes a TODO and wants the synthesized Issue
    to fall out of /act and /briefing automatically. Off by default
    because LLM titles can drift slightly between runs (same TODO,
    different slug → false-positive stale).
    """
    _load_dotenv(get_workspace_path(workspace) / ".env")
    client = get_client()
    extracted_by = client.label()
    db = builder.connect(workspace)

    stats = Stats()
    _enrich_issues(client, db, extracted_by, stats)
    _enrich_notes(client, db, extracted_by, stats, prune_stale=prune_stale)
    return stats


# ---------- Issue path (concepts only) ----------

def _enrich_issues(client: LLMClient, db, extracted_by: str, stats: Stats) -> None:
    issues = db.query("SELECT id, source, external_key, title, body FROM Issue;")
    for issue in issues or []:
        # Skip Issues we synthesized from Notes — re-running enrichment over
        # them would double-extract concepts that already came from the source
        # note's pass.
        if issue.get("source") == "note":
            continue
        text = _join_text(issue.get("title"), issue.get("body"))
        if not text:
            continue
        try:
            concepts = _call_concepts(client, text)
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"issue {issue.get('external_key')}: {exc}")
            continue
        stats.issues_processed += 1
        _attach_concepts(db, issue["id"], concepts, extracted_by, stats)


# ---------- Note path (concepts + action items) ----------

def _enrich_notes(
    client: LLMClient, db, extracted_by: str, stats: Stats,
    prune_stale: bool = False,
) -> None:
    notes = db.query("SELECT id, source, path, title, body FROM Note;")
    for note in notes or []:
        text = _join_text(note.get("title"), note.get("body"))
        if not text:
            continue
        try:
            payload = _call_note(client, text)
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"note {note.get('path')}: {exc}")
            continue
        stats.notes_processed += 1

        # Concepts the LLM extracted from the note are not attached to the
        # Note itself — schema has no Note->Concept edge yet. They get
        # attached to each synthesized Issue below instead, since the
        # action items inherit the note's topical context.

        new_keys: set[str] = set()
        for item in payload.get("action_items") or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            confidence = float(item.get("confidence", 0.7))
            status = (item.get("status") or "open").strip().lower()
            if status not in ("open", "done"):
                status = "open"

            external_key = _action_item_key(note.get("path"), title)
            new_keys.add(external_key)
            issue_id = builder.upsert_issue(
                db,
                source="note",
                external_key=external_key,
                title=title,
                status=status,
                body=None,
            )
            builder.relate(
                db, issue_id, "extracted_from", note["id"],
                confidence=confidence,
                extracted_by=extracted_by,
            )
            _attach_concepts(
                db, issue_id, payload.get("concepts") or [],
                extracted_by, stats,
            )
            stats.action_items_extracted += 1
            stats.edges_created += 1

        if prune_stale:
            stats.stale_marked += _mark_stale(db, note["id"], new_keys)


def _mark_stale(db, note_id, current_keys: set[str]) -> int:
    """Mark Issues previously extracted from this note as 'stale' when
    they're no longer in the current re-extraction. Operates only on
    `source='note'` Issues so it can't accidentally touch human-curated
    Issues that happen to have an extracted_from edge for some other
    reason. Returns the count marked stale."""
    rows = db.query(
        "SELECT in.external_key AS key, in.status AS status "
        "FROM extracted_from WHERE out = $note;",
        {"note": note_id},
    )
    stale = 0
    for row in rows or []:
        key = row.get("key")
        if not key or key in current_keys:
            continue
        # Don't overwrite if already stale or already done — `done` is a
        # legitimate end state from a checkbox `- [x]` and shouldn't be
        # downgraded to stale.
        if (row.get("status") or "").lower() in ("stale", "done"):
            continue
        db.query(
            "UPDATE Issue SET status = 'stale' "
            "WHERE source = 'note' AND external_key = $key;",
            {"key": key},
        )
        stale += 1
    return stale


def _action_item_key(note_path: str | None, title: str) -> str:
    """Stable identifier so re-running enrichment doesn't duplicate Issues.

    Uses the note path + a slug of the title. Schema's UNIQUE index on
    (source, external_key) does the dedup.
    """
    base = note_path or "_unknown"
    return f"{base}#{builder._slugify(title)}"  # noqa: SLF001


# ---------- shared helpers ----------

def _join_text(title: str | None, body: str | None) -> str:
    return f"{title or ''}\n\n{body or ''}".strip()


def _attach_concepts(
    db, target_id, concepts: list[dict],
    extracted_by: str, stats: Stats,
) -> None:
    for concept in concepts:
        name = (concept.get("name") or "").strip()
        if not name:
            continue
        concept_id = builder.upsert_concept(db, name)
        builder.relate(
            db, target_id, "mentions", concept_id,
            confidence=float(concept.get("confidence", 0.7)),
            provenance="extracted",
            extracted_by=extracted_by,
        )
        stats.concepts_extracted += 1
        stats.edges_created += 1


def _call_concepts(client: LLMClient, text: str) -> list[dict]:
    raw = client.ask(ISSUE_SYSTEM_PROMPT, text)
    parsed = _parse_json(raw)
    return parsed if isinstance(parsed, list) else []


def _call_note(client: LLMClient, text: str) -> dict:
    raw = client.ask(NOTE_SYSTEM_PROMPT, text)
    parsed = _parse_json(raw)
    return parsed if isinstance(parsed, dict) else {}


def _parse_json(content: str):
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[: content.rfind("```")].rstrip()
    return json.loads(content)


def main() -> None:
    import argparse

    # Backwards-compat: `python -m library.enrichment` and
    # `python -m library.enrichment --prune-stale` (no subcommand) both
    # mean "run the full LLM-driven enrichment". Route those to the
    # `run` subcommand so existing automation keeps working — but let
    # `-h` / `--help` fall through to the top-level subcommand listing.
    argv = sys.argv[1:]
    known_cmds = {"run", "targets", "apply"}
    help_flags = {"-h", "--help"}
    if not argv:
        argv = ["run"]
    elif argv[0] not in known_cmds and argv[0] not in help_flags:
        argv = ["run"] + argv

    parser = argparse.ArgumentParser(prog="library.enrichment",
                                     description="L2 enrichment over Issues + Notes")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run",
                           help="Full LLM-driven enrichment (default).")
    p_run.add_argument(
        "--prune-stale", action="store_true",
        help="Mark Issues as 'stale' when they were previously extracted "
             "from a Note but no longer appear in the current re-extraction.",
    )

    p_targets = sub.add_parser(
        "targets",
        help="Print Issues and Notes that need enrichment as JSON. "
             "Used by the /enrich skill so Claude Code itself can do the "
             "extraction without an API key.",
    )
    p_targets.add_argument(
        "--all", action="store_true",
        help="Include items already enriched (default skips them).",
    )

    p_apply = sub.add_parser(
        "apply",
        help="Apply pre-computed enrichment results from a JSON file. "
             "Inverse of `targets`: results in, edges out.",
    )
    p_apply.add_argument("--from", dest="from_file", required=True,
                         help="Path to the results JSON.")
    p_apply.add_argument("--extracted-by", default="claude-code-skill",
                         help="Provenance label written onto every edge.")
    p_apply.add_argument("--prune-stale", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        stats = enrich(prune_stale=args.prune_stale)
        print(f"[enrichment] {stats}")
    elif args.cmd == "targets":
        targets = list_targets(new_only=not args.all)
        json.dump(targets, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    elif args.cmd == "apply":
        with open(args.from_file) as f:
            payload = json.load(f)
        stats = apply_results(
            payload,
            extracted_by=args.extracted_by,
            prune_stale=args.prune_stale,
        )
        print(f"[enrichment.apply] {stats}")


if __name__ == "__main__":
    main()
