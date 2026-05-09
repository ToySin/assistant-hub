# /meeting-note — Fetch and summarize recent meeting notes

Surfaces Gemini meeting notes that the workspace's `gdrive_gemini`
source has already ingested as `Note` rows. Picks one, summarizes,
and offers structured follow-ups.

For raw Drive API access (when ingestion is stale or you want a file
not yet picked up), see hub's `google-workspace.md` patterns.

## Prerequisites

- `gdrive_gemini` source enabled in `<workspace>/sources.yaml`
- `gcloud auth application-default login` already done on this laptop

## Procedure

### Step 1. Refresh first (cheap)

```bash
python -m library.sources.run --source gdrive_gemini
```

If this fails (auth, network), proceed with whatever's already in the
graph and tell the user data may be stale.

### Step 2. Pick the meeting

Args:

| Arg | Behavior |
|-----|----------|
| (none) | List the 10 most recent gdrive_gemini Notes; let the user pick |
| `<keyword>` | Filter by title CONTAINS keyword (case-insensitive) |
| `--days <N>` | Limit window to last N days (default: 7) |

Query:

```python
db.query("""
SELECT id, title, modified_at, path
FROM Note
WHERE source = 'gdrive_gemini'
  AND modified_at >= $cutoff
  AND ($kw IS NONE OR string::lowercase(title) CONTAINS string::lowercase($kw))
ORDER BY modified_at DESC
LIMIT 10;
""")
```

If exactly one result, auto-select. Otherwise show:

```
| # | Date | Title | Drive |
```

### Step 3. Read the body

```python
db.query("SELECT body FROM Note WHERE id = $id;", {"id": picked_id})
```

The Gemini export is plain-text-ish; sections are typically
"Attendees", "Summary", "Details", "Action Items".

### Step 4. Summarize (in-session)

Read the body and produce:

```markdown
## <title> — <date>

### Attendees
- ...

### Summary
- 3–5 bullets, decisions and key topics only

### Details
- Organized faithfully to the source's "Details" section

### Action Items
- Owner / what / by when (extract verbatim where possible)

### Items relevant to me
- Anything that mentions the user, their team, or projects in dashboard.yaml
```

Don't invent owners or dates. If the source is ambiguous, mark as
"(unclear)" rather than guessing.

### Step 5. Offer follow-ups

Then ask, one menu line:

> 다음 중 할까요?
> 1. notes에 저장 (`/note "<short summary>"`)
> 2. 아이디어로 캡처 (`/idea capture "..."`) — 후속 작업거리가 있을 때
> 3. dashboard action_items 추가 (`/action-item "..."`)
> 4. 그냥 종료

Don't auto-execute. The user picks.

## Notes

- The "Items relevant to me" filter uses `dashboard.yaml` projects /
  focus / blockers as the relevance signal. Without those filled in,
  the section will be empty (and that's fine).
- If multiple meetings match the keyword, prefer the more recent one
  unless the user explicitly picks otherwise.
