#!/usr/bin/env bash
# Populate a workspace's .claude/{commands,skills}/ with relative symlinks
# to assistant-hub's source-of-truth slash command files and the helper
# documents those commands delegate into (e.g. ws-config branch files).
#
# Idempotent — re-running picks up any new commands/skills and refreshes
# stale symlinks. Existing non-symlink files are left alone.
#
# Usage:
#   link-commands.sh                # link into the cwd
#   link-commands.sh <workspace>    # link into the given workspace dir

set -euo pipefail

HUB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

TARGET="${1:-.}"
TARGET="$(cd "$TARGET" && pwd)"

# Per-file symlinks for .claude/commands/ — the directory itself stays
# real so the workspace can later add its own private commands without
# pulling in everything from upstream.
link_commands() {
    local src_dir="$HUB_ROOT/.claude/commands"
    local dest_dir="$TARGET/.claude/commands"
    [[ -d "$src_dir" ]] || return 0
    mkdir -p "$dest_dir"
    local rel
    rel="$(realpath --relative-to="$dest_dir" "$src_dir")"
    for src in "$src_dir"/*.md; do
        [[ -e "$src" ]] || continue
        local name dest
        name="$(basename "$src")"
        dest="$dest_dir/$name"
        if [[ -L "$dest" || ! -e "$dest" ]]; then
            ln -sfn "$rel/$name" "$dest"
            echo "linked: commands/$name"
        else
            echo "skip:   commands/$name (existing non-symlink)"
        fi
    done
}

# Whole-directory symlink for .claude/skills/ — these are private helper
# documents the slash commands delegate into. We don't expect workspaces
# to add their own sub-skills here, so a single dir symlink keeps things
# tidy and any new sub-skill in the upstream tree appears automatically.
link_skills() {
    local src_dir="$HUB_ROOT/.claude/skills"
    local dest="$TARGET/.claude/skills"
    [[ -d "$src_dir" ]] || return 0
    mkdir -p "$TARGET/.claude"
    local rel
    rel="$(realpath --relative-to="$TARGET/.claude" "$src_dir")"
    if [[ -e "$dest" && ! -L "$dest" ]]; then
        echo "skip:   skills/ (existing non-symlink directory)"
        return 0
    fi
    ln -sfn "$rel" "$dest"
    echo "linked: skills -> $rel"
}

link_commands
link_skills
