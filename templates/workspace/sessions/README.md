# sessions/

Snapshots of Claude Code session jsonl files for cross-laptop continuity.

## Files
- `<session-id>.jsonl` — full conversation log for a Claude Code session
- `manifest.txt` — TSV (session-id, last-synced-utc, encoded-cwd)

## Push from laptop A
```bash
ASSISTHUB_WORKSPACE={{WORKSPACE_NAME}} \
  ~/repositories/assistant-hub/scripts/sync-session.sh
git add sessions && git commit -m "sync session <id>" && git push
```

## Resume on laptop B
```bash
git pull
ASSISTHUB_WORKSPACE={{WORKSPACE_NAME}} \
  ~/repositories/assistant-hub/scripts/restore-session.sh
claude --resume <session-id>
```

## Caveats
- Restore requires the same `$HOME` path on both laptops (sessions are keyed by encoded cwd).
- jsonl files contain full conversation content — keep this repo private.
- Resume only works while the session is recent; very old sessions may not load.
