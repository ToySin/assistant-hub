#!/usr/bin/env bash
# PostToolUse hook for Bash. Only invokes auto-sync.sh when the bash
# command touched graph state — running ETL, capturing/promoting an
# idea, bootstrapping the dashboard, or running enrichment. Other Bash
# calls are no-ops, so the hook doesn't slow down day-to-day work.

set -euo pipefail

cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null || echo "")

case "$cmd" in
    *library.sources*|*library.ideas*|*library.dashboard*|*library.enrichment*|*graph.sync*)
        exec "$(dirname "$0")/auto-sync.sh"
        ;;
esac
