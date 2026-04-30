#!/usr/bin/env bash
# Auto-sync workspace graph exports on Claude Code Stop event.
#
# - Exits 0 silently if no workspace is active or no graph DB exists yet
#   (so non-assistant-hub sessions are unaffected).
# - Refreshes <workspace>/exports/graph/*.jsonl from the current DB.
# - Commits the diff with an "auto-sync" message. Does NOT push —
#   pushing stays a deliberate action.
#
# Wire from settings.json:
#   "hooks": {
#     "Stop": [
#       {"hooks": [{"type": "command",
#                   "command": "/home/dongbin/repositories/assistant-hub/scripts/auto-sync.sh"}]}
#     ]
#   }

set -euo pipefail

WORKSPACE="${ASSISTHUB_WORKSPACE:-}"
[[ -z "$WORKSPACE" ]] && exit 0

LOCATION="${ASSISTHUB_LOCATION:-$HOME/repositories}"
WS_DIR="$LOCATION/assisthub-ws-$WORKSPACE"
[[ ! -d "$WS_DIR/db/graph.surrealkv" ]] && exit 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PY="$HUB_ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 || true)"
[[ -z "$PY" ]] && exit 0

# Refresh exports. Swallow errors — we don't want to abort Claude's Stop
# pipeline because of a transient DB issue.
PYTHONPATH="$HUB_ROOT" "$PY" -m graph.sync >/dev/null 2>&1 || exit 0

cd "$WS_DIR"
if git diff --quiet exports/ && [[ -z "$(git ls-files --others --exclude-standard exports/)" ]]; then
    exit 0
fi

git add exports/
git commit -q -m "auto-sync: refresh graph exports

Co-Authored-By: Claude Code (auto-sync hook) <noreply@anthropic.com>"
