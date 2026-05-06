#!/usr/bin/env bash
# Bootstrap a fresh laptop for assistant-hub work.
#
# Usage:
#   ./scripts/setup.sh <workspace-name>
#
# What it does (all idempotent — re-running is safe):
#   1. Clones assistant-hub if missing
#   2. Clones assisthub-ws-<workspace-name> if missing
#   3. Installs git hooks (pre-commit + pre-push) on both
#   4. Creates the assistant-hub venv and installs Python deps
#   5. Sets the active workspace pointer (assisthub use)
#   6. Restores session jsonl files from the workspace
#   7. Prints `claude --resume <id>` for the most recent session
#
# Env overrides (same convention as new-workspace.sh):
#   ASSISTHUB_GH_OWNER   GitHub owner (default: current `gh` user)
#   ASSISTHUB_LOCATION   workspace base directory (default: ~/repositories)
#
# Self-bootstrapping curl-pipe-bash form (inspect first if you didn't write it):
#   bash <(curl -sSL https://raw.githubusercontent.com/<owner>/assistant-hub/main/scripts/setup.sh) <workspace>

set -euo pipefail

WORKSPACE="${1:-}"
if [[ -z "$WORKSPACE" || "$WORKSPACE" == "-h" || "$WORKSPACE" == "--help" ]]; then
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

LOCATION="${ASSISTHUB_LOCATION:-$HOME/repositories}"

# --- prerequisites ---
for cmd in gh git python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: $cmd not found on PATH" >&2
        exit 1
    fi
done
if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: gh is not authenticated. Run \`gh auth login\` first." >&2
    exit 1
fi

OWNER="${ASSISTHUB_GH_OWNER:-$(gh api user --jq .login)}"
mkdir -p "$LOCATION"

# --- 1. clone assistant-hub ---
HUB="$LOCATION/assistant-hub"
if [[ -d "$HUB/.git" ]]; then
    echo "==> assistant-hub already at $HUB (skipping clone)"
else
    echo "==> cloning $OWNER/assistant-hub -> $HUB"
    gh repo clone "$OWNER/assistant-hub" "$HUB"
fi

# --- 2. clone workspace ---
WS_REPO="assisthub-ws-$WORKSPACE"
WS="$LOCATION/$WS_REPO"
if [[ -d "$WS/.git" ]]; then
    echo "==> $WS_REPO already at $WS (skipping clone)"
else
    echo "==> cloning $OWNER/$WS_REPO -> $WS"
    gh repo clone "$OWNER/$WS_REPO" "$WS"
fi

# --- 3. install git hooks (idempotent — copies fresh each time) ---
echo "==> installing git hooks"
"$HUB/scripts/install-hooks.sh" "$HUB" >/dev/null
"$HUB/scripts/install-hooks.sh" "$WS" >/dev/null

# --- 4. venv + deps ---
DEPS=(surrealdb requests pyyaml anthropic)

ensure_uv() {
    command -v uv >/dev/null 2>&1 && return 0
    [[ -x "$HOME/.local/bin/uv" ]] && return 0
    if command -v pip3 >/dev/null 2>&1; then
        echo "==> installing uv (pip3 --user)"
        pip3 install --user --quiet uv
        return 0
    fi
    return 1
}

resolve_uv() {
    if command -v uv >/dev/null 2>&1; then echo uv
    else echo "$HOME/.local/bin/uv"
    fi
}

if [[ -d "$HUB/.venv" ]]; then
    echo "==> venv already at $HUB/.venv (skipping create)"
else
    echo "==> creating venv at $HUB/.venv"
    if ensure_uv; then
        UV="$(resolve_uv)"
        "$UV" venv "$HUB/.venv" >/dev/null
        "$UV" pip install --quiet --python "$HUB/.venv/bin/python" "${DEPS[@]}"
    elif python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
        python3 -m venv "$HUB/.venv"
        "$HUB/.venv/bin/pip" install --quiet "${DEPS[@]}"
    else
        echo "WARNING: could not create venv (no uv, no python3-venv)" >&2
        echo "         install one and re-run, or set up the venv by hand." >&2
    fi
fi

# --- 5. workspace pointer ---
echo "==> setting active workspace = $WORKSPACE"
"$HUB/scripts/assisthub" use "$WORKSPACE" >/dev/null

# --- 6. restore session jsonl ---
if [[ -d "$WS/sessions" ]]; then
    echo "==> restoring session jsonl files"
    ASSISTHUB_WORKSPACE="$WORKSPACE" "$HUB/scripts/restore-session.sh" >/dev/null || true
fi

# --- 7. summary ---
echo
echo "Done."
echo "  assistant-hub: $HUB"
echo "  workspace:     $WS"
echo "  active set:    $WORKSPACE"
echo
LATEST=""
if [[ -d "$WS/sessions" ]]; then
    LATEST="$(ls -t "$WS/sessions"/*.jsonl 2>/dev/null | head -n1 || true)"
fi
if [[ -n "$LATEST" ]]; then
    SID="$(basename "$LATEST" .jsonl)"
    echo "Resume the most recent session:"
    echo "  claude --resume $SID"
    echo
fi
echo "Optional: add ANTHROPIC_API_KEY to $WS/.env if you want /enrichment to run."
echo "Optional: ln -s $HUB/scripts/assisthub ~/.local/bin/assisthub  (puts \`assisthub\` on PATH)"
