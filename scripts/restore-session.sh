#!/usr/bin/env bash
# Restore session jsonl from the active workspace into Claude Code's projects dir.
# Run this on a fresh laptop after cloning the workspace repo, then resume with
#   claude --resume <session-id>
#
# Usage:
#   restore-session.sh                # restore all sessions in manifest
#   restore-session.sh <session-id>   # restore one session by ID
#
# Refuses to overwrite existing files unless --force is passed.

set -euo pipefail

WORKSPACE_NAME="${ASSISTHUB_WORKSPACE:-}"
if [[ -z "${WORKSPACE_NAME}" ]]; then
    echo "ERROR: ASSISTHUB_WORKSPACE not set" >&2
    exit 1
fi

LOCATION="${ASSISTHUB_LOCATION:-${HOME}/repositories}"
WORKSPACE_DIR="${LOCATION}/assisthub-ws-${WORKSPACE_NAME}"
SESSIONS_DIR="${WORKSPACE_DIR}/sessions"
if [[ ! -d "${SESSIONS_DIR}" ]]; then
    echo "ERROR: workspace sessions dir not found: ${SESSIONS_DIR}" >&2
    exit 1
fi

PROJECTS_DIR="${HOME}/.claude/projects"
ENCODED_CWD="$(echo "-${HOME#/}" | tr '/' '-')"
DEST_DIR="${PROJECTS_DIR}/${ENCODED_CWD}"
mkdir -p "${DEST_DIR}"

FORCE=0
SESSION_ID=""
for arg in "$@"; do
    case "${arg}" in
        --force) FORCE=1 ;;
        -*) echo "ERROR: unknown flag ${arg}" >&2; exit 1 ;;
        *) SESSION_ID="${arg}" ;;
    esac
done

restore_one() {
    local id="$1"
    local src="${SESSIONS_DIR}/${id}.jsonl"
    local dst="${DEST_DIR}/${id}.jsonl"
    if [[ ! -f "${src}" ]]; then
        echo "skip: ${id} (not in workspace)"
        return
    fi
    if [[ -f "${dst}" && "${FORCE}" -ne 1 ]]; then
        echo "skip: ${id} (exists at ${dst}, pass --force to overwrite)"
        return
    fi
    cp "${src}" "${dst}"
    echo "restored: ${id}"
}

if [[ -n "${SESSION_ID}" ]]; then
    restore_one "${SESSION_ID}"
else
    MANIFEST="${SESSIONS_DIR}/manifest.txt"
    if [[ ! -f "${MANIFEST}" ]]; then
        echo "ERROR: no manifest at ${MANIFEST}" >&2
        exit 1
    fi
    while IFS=$'\t' read -r id ts cwd; do
        [[ -z "${id}" || "${id}" == \#* ]] && continue
        restore_one "${id}"
    done < "${MANIFEST}"
fi

echo "next: claude --resume <session-id> from cwd ${HOME}"
