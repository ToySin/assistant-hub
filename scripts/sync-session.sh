#!/usr/bin/env bash
# Sync a Claude Code session jsonl into the active workspace's sessions/ dir.
#
# Usage:
#   sync-session.sh                # sync most recently modified session
#   sync-session.sh <session-id>   # sync a specific session by ID
#
# Requires:
#   ASSISTHUB_WORKSPACE  active workspace short name
#   ASSISTHUB_LOCATION   (optional) workspaces root, defaults to ~/repositories
#
# This script copies (does not symlink) the jsonl, so the workspace repo
# stays self-contained for cross-laptop transport via git. Re-run to refresh.

set -euo pipefail

WORKSPACE_NAME="${ASSISTHUB_WORKSPACE:-}"
if [[ -z "${WORKSPACE_NAME}" ]]; then
    echo "ERROR: ASSISTHUB_WORKSPACE not set" >&2
    exit 1
fi

LOCATION="${ASSISTHUB_LOCATION:-${HOME}/repositories}"
WORKSPACE_DIR="${LOCATION}/assisthub-ws-${WORKSPACE_NAME}"
if [[ ! -d "${WORKSPACE_DIR}" ]]; then
    echo "ERROR: workspace not found: ${WORKSPACE_DIR}" >&2
    exit 1
fi

# Claude Code stores sessions under ~/.claude/projects/<encoded-cwd>/<id>.jsonl
# where encoded-cwd replaces '/' with '-' (e.g. /home/dongbin -> -home-dongbin).
PROJECTS_DIR="${HOME}/.claude/projects"
ENCODED_CWD="$(echo "-${HOME#/}" | tr '/' '-')"
SESSION_DIR="${PROJECTS_DIR}/${ENCODED_CWD}"
if [[ ! -d "${SESSION_DIR}" ]]; then
    echo "ERROR: Claude session dir not found: ${SESSION_DIR}" >&2
    exit 1
fi

SESSION_ID="${1:-}"
if [[ -z "${SESSION_ID}" ]]; then
    SRC="$(ls -t "${SESSION_DIR}"/*.jsonl 2>/dev/null | head -n1 || true)"
    if [[ -z "${SRC}" ]]; then
        echo "ERROR: no session jsonl files found in ${SESSION_DIR}" >&2
        exit 1
    fi
    SESSION_ID="$(basename "${SRC}" .jsonl)"
else
    SRC="${SESSION_DIR}/${SESSION_ID}.jsonl"
    if [[ ! -f "${SRC}" ]]; then
        echo "ERROR: session not found: ${SRC}" >&2
        exit 1
    fi
fi

DST_DIR="${WORKSPACE_DIR}/sessions"
mkdir -p "${DST_DIR}"
DST="${DST_DIR}/${SESSION_ID}.jsonl"
cp "${SRC}" "${DST}"

MANIFEST="${DST_DIR}/manifest.txt"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
touch "${MANIFEST}"
if grep -q "^${SESSION_ID}\b" "${MANIFEST}" 2>/dev/null; then
    # update timestamp for existing entry
    grep -v "^${SESSION_ID}\b" "${MANIFEST}" > "${MANIFEST}.tmp" || true
    mv "${MANIFEST}.tmp" "${MANIFEST}"
fi
echo "${SESSION_ID}	${TIMESTAMP}	${ENCODED_CWD}" >> "${MANIFEST}"

echo "synced: ${SESSION_ID} -> ${DST}"
echo "next: cd ${WORKSPACE_DIR} && git add sessions && git commit -m 'sync session ${SESSION_ID}'"
