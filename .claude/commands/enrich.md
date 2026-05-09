# /enrich — Claude-driven Layer 2 enrichment

Runs concept + action-item extraction using *this* Claude Code session
as the LLM, instead of `python -m library.enrichment run` (which calls
Anthropic / Ollama / OpenAI under its own API key).

Use this when:
- The workspace doesn't have an LLM API key wired up
- You want on-demand enrichment instead of a scheduled job
- You're already in a session and the cost is sunk anyway

For automated/scheduled enrichment, prefer the `run` path — it doesn't
need a human-in-the-loop.

## Prerequisites

- `ASSISTHUB_WORKSPACE` is set (or the active pointer is correct).
- An ETL has populated the graph (`python -m library.sources.run`).

## Procedure

### Step 1. Get pending targets

```bash
python -m library.enrichment targets
```

Returns JSON of the form:

```
{
  "issues": [{"source", "external_key", "title", "body"}, ...],
  "notes":  [{"source", "path", "title", "body"}, ...]
}
```

By default this skips items already enriched (Issues with any
`mentions` edge, Notes with any `extracted_from` edge). Use
`targets --all` to re-extract over everything.

If both lists are empty, report "nothing to enrich" and stop.

### Step 2. Extract concepts (and action items, for Notes)

For **each Issue**, read `title + body` and produce a `concepts` list.
For **each Note**, produce both `concepts` and `action_items`.

#### Concept rules

Concepts are:
- Technical components / services / technologies (e.g. "Redis", "HPA", "SurrealDB")
- Domain concepts specific to the work (e.g. "auto-sync", "session continuity")
- Specific tools / libraries / commands (e.g. "Anthropic SDK", "/briefing", "gh CLI")

NOT concepts:
- Generic words ("issue", "TODO", "feature", "system")
- Bare letters / abbreviations without context
- Filler ("the", "a", "this")

Confidence rubric:
- 0.95+ for explicit verbatim mentions
- 0.7–0.9 for clearly inferred concepts
- below 0.7 only when the connection is ambiguous

#### Action-item rules (Notes only)

Only items the author wrote *as an action they need to take*. Strong
signals: explicit "TODO:", checkbox lines (`- [ ]`, `- [x]`),
imperative phrases ("ask Bob about ...", "fix Y by Friday").

Mark `status: "done"` for already-completed items (e.g. `- [x]`).

NOT action items:
- Vague intentions or musings ("I should think about ...")
- Observations or notes-to-self that aren't asks
- Items already completed and clearly archived (unless an explicit `- [x]`)

If a note has no clear action items, return an empty list. Same for
concepts.

### Step 3. Build the apply payload

Write the results to a temporary JSON file with this shape:

```json
{
  "issues": [
    {
      "source": "github",
      "external_key": "ToySin/orockgarock#1",
      "concepts": [{"name": "Neon", "confidence": 0.98}, ...]
    }
  ],
  "notes": [
    {
      "source": "markdown_dirs",
      "path": "/abs/path/to/note.md",
      "concepts": [{"name": "...", "confidence": 0.8}],
      "action_items": [
        {"title": "Ask Bob about migration", "status": "open", "confidence": 0.9}
      ]
    }
  ]
}
```

Keys must match what `targets` returned — the `apply` step looks up
nodes by `(source, external_key)` for Issues and `(source, path)` for
Notes.

A scratch path under the workspace is fine, e.g.
`<workspace>/exports/.enrich-payload.json`. Clean up after.

### Step 4. Apply to the graph

```bash
python -m library.enrichment apply \
  --from <payload-file> \
  --extracted-by "claude-code:<model_id>"
```

The `--extracted-by` label is recorded on every edge for provenance —
it's how at-rest queries can tell `/enrich`-produced edges apart from
script-produced ones. Use the actual model id (e.g. `claude-opus-4-7`)
so future debugging knows exactly what extracted what.

Report the printed `Stats(...)` line verbatim.

### Step 5. (Optional) Mark stale action items

If you re-ran over Notes and want previously-extracted action items
that no longer appear to fall out of `/act` and `/briefing`, re-run
step 4 with `--prune-stale`. Off by default because LLM-generated
action-item titles can drift slightly between runs (same TODO,
different wording → false-positive stale).

## Notes

- The Python module is the data layer. This skill is the
  extraction-and-glue layer — don't reimplement node lookup or edge
  writing in the skill, let `apply` do it.
- For large backlogs, batch issues — running 50+ extractions in a
  single turn is fine, but keeping each issue's extraction visible in
  the conversation makes corrections easier than a giant bulk dump.
- Re-runs are cheap: `targets` skips already-enriched items by default,
  so calling `/enrich` repeatedly only processes deltas.
