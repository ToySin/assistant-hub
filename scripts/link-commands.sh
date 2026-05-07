#!/usr/bin/env bash
# Populate a workspace's .claude/commands/ with relative symlinks to
# assistant-hub's source-of-truth slash command files.
#
# Idempotent — re-running picks up any new commands and refreshes any
# stale symlinks. Existing files (non-symlinks) are left alone.
#
# Usage:
#   link-commands.sh                # link into the cwd
#   link-commands.sh <workspace>    # link into the given workspace dir

set -euo pipefail

HUB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$HUB_ROOT/.claude/commands"

TARGET="${1:-.}"
TARGET="$(cd "$TARGET" && pwd)"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "ERROR: source dir missing: $SRC_DIR" >&2
    exit 1
fi

DEST_DIR="$TARGET/.claude/commands"
mkdir -p "$DEST_DIR"

# Compute the relative path from the workspace's .claude/commands to the
# source. e.g. ../../../assistant-hub/.claude/commands when both repos
# are siblings under ~/repositories/.
REL="$(realpath --relative-to="$DEST_DIR" "$SRC_DIR")"

for src in "$SRC_DIR"/*.md; do
    [[ -e "$src" ]] || continue
    name="$(basename "$src")"
    dest="$DEST_DIR/$name"
    if [[ -L "$dest" || ! -e "$dest" ]]; then
        ln -sfn "$REL/$name" "$dest"
        echo "linked: $name -> $REL/$name"
    else
        echo "skip:   $name (existing non-symlink)"
    fi
done
