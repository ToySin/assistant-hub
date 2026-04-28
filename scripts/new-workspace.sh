#!/usr/bin/env bash
#
# new-workspace.sh — bootstrap a new assistant-hub workspace repo.
#
# Usage:
#   ./scripts/new-workspace.sh <name> [--no-push] [--owner <gh-owner>] [--location <dir>]
#
# Creates: <location>/assisthub-ws-<name>/  (default location: ~/repositories)
# Pushes:  https://github.com/<owner>/assisthub-ws-<name>  (private)
#
# Env overrides:
#   ASSISTHUB_GH_OWNER   — GitHub owner (default: current `gh` user)
#   ASSISTHUB_LOCATION   — base directory (default: ~/repositories)

set -euo pipefail

# --- Resolve repo root (assistant-hub) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_DIR="$HUB_ROOT/templates/workspace"

# --- Parse args ---
NAME=""
PUSH=1
OWNER="${ASSISTHUB_GH_OWNER:-}"
LOCATION="${ASSISTHUB_LOCATION:-$HOME/repositories}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-push)   PUSH=0; shift ;;
    --owner)     OWNER="$2"; shift 2 ;;
    --location)  LOCATION="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) echo "Unknown flag: $1" >&2; exit 2 ;;
    *)
      if [[ -z "$NAME" ]]; then NAME="$1"; shift
      else echo "Unexpected arg: $1" >&2; exit 2; fi
      ;;
  esac
done

if [[ -z "$NAME" ]]; then
  echo "Usage: $0 <name> [--no-push] [--owner <gh-owner>] [--location <dir>]" >&2
  exit 2
fi

# --- Validate name (lowercase, alnum + dash) ---
if ! [[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Invalid name '$NAME' — use lowercase letters, digits, dashes (must start with alnum)." >&2
  exit 2
fi

REPO_NAME="assisthub-ws-$NAME"
TARGET_DIR="$LOCATION/$REPO_NAME"

if [[ -e "$TARGET_DIR" ]]; then
  echo "Target already exists: $TARGET_DIR" >&2
  exit 1
fi

# --- Resolve GitHub owner if pushing ---
if [[ $PUSH -eq 1 && -z "$OWNER" ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "gh CLI not found — install gh or pass --no-push." >&2
    exit 1
  fi
  OWNER="$(gh api user --jq .login)"
  if [[ -z "$OWNER" ]]; then
    echo "Could not determine GitHub owner (gh auth status?)." >&2
    exit 1
  fi
fi

# --- Copy template & substitute ---
echo "==> Creating $TARGET_DIR"
mkdir -p "$LOCATION"
cp -R "$TEMPLATE_DIR" "$TARGET_DIR"

# Substitute placeholders in text files
find "$TARGET_DIR" -type f \( -name '*.md' -o -name '*.yaml' \) -print0 \
  | xargs -0 sed -i "s/{{WORKSPACE_NAME}}/$NAME/g"

# --- Init git ---
echo "==> Initializing git"
cd "$TARGET_DIR"
git init -q -b main
git add .
git commit -q -m "Initial commit — assisthub-ws-$NAME"

# --- Create + push GitHub repo ---
if [[ $PUSH -eq 1 ]]; then
  echo "==> Creating GitHub repo $OWNER/$REPO_NAME (private)"
  gh repo create "$OWNER/$REPO_NAME" --private \
    --description "assistant-hub workspace: $NAME" \
    --source=. --remote=origin --push
fi

echo
echo "Done."
echo "  Local:  $TARGET_DIR"
if [[ $PUSH -eq 1 ]]; then
  echo "  Remote: https://github.com/$OWNER/$REPO_NAME"
fi
echo
echo "Next:"
echo "  cd $TARGET_DIR"
echo "  cp .env.example .env   # fill credentials"
echo "  edit sources.yaml      # declare data sources"
