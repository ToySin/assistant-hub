# /search — Local FTS over indexed text

Full-text search across every Issue / PR body the workspace has
ingested. Sidecar to the SurrealDB graph — graph for nodes/edges,
search for raw-text keyword queries.

## Prerequisites

- `ASSISTHUB_WORKSPACE` is set or pointer is configured.
- ETL has run at least once (so docs got indexed). Each source's
  sync hook writes into the search index automatically; no separate
  sync step is needed.

## Procedure

### Quick query

```bash
python -m library.search "redis OOM"
python -m library.search "concept extraction" --source github --limit 5
```

Output is bm25-ranked. The most negative `rank` wins (FTS5 convention
— the closer to zero on the negative side, the better the match;
sorted ascending so top is best).

FTS5 syntax cheat sheet:
- `phrase queries` — quote them: `"redis cache"`
- `AND / OR / NOT` — `redis NOT vector`, `briefing OR act`
- prefix — `monit*`
- column-targeted — `title:redis` (columns: title / body / author)

### Index health

```bash
python -m library.search stats
```

Shows per-source document counts and last-sync timestamps. If a source
is missing or stale, run `python -m library.sources.run` (or
`--full` to rebuild).

### Use during a task

When investigating something the user mentioned by phrase ("the
auto-sync issue", "what was that PR about HPA"), prefer search over
scanning the dashboard or issue list — it's the lowest-effort way to
find the right ticket.

## Notes

- The DB lives at `<workspace>/db/search.db` (gitignored, regenerable
  from sources). Re-running ETL keeps the index in sync via the
  upsert hooks in `library/sources/*.py`.
- Tokenizer is `unicode61 remove_diacritics 2`. Korean recall is OK
  for unique nouns but weak for inflected text — when Confluence /
  Korean docs land, plan to add a parallel `documents_fts_trigram`
  table per the #6 research notes.
