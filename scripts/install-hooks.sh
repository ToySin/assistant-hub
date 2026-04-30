#!/usr/bin/env bash
# Install assistant-hub git hooks into a target repo's .git/hooks/.
#
# Usage:
#   install-hooks.sh                # install into current dir's repo
#   install-hooks.sh <repo-path>    # install into the given repo
#
# Hooks live in scripts/hooks/ in this repo (the source of truth). They
# are copied (not symlinked) so the target repo does not break if
# assistant-hub is later moved on disk.

set -euo pipefail

HUB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$HUB_ROOT/scripts/hooks"
TARGET="${1:-.}"
TARGET="$(cd "$TARGET" && pwd)"

if [[ ! -d "$TARGET/.git" ]]; then
    echo "ERROR: $TARGET is not a git repo" >&2
    exit 1
fi

DEST_DIR="$TARGET/.git/hooks"
mkdir -p "$DEST_DIR"

for hook in "$SRC_DIR"/*; do
    name=$(basename "$hook")
    cp "$hook" "$DEST_DIR/$name"
    chmod +x "$DEST_DIR/$name"
    echo "installed: $name -> $DEST_DIR/$name"
done
