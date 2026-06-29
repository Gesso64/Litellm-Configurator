#!/usr/bin/env bash
# Launch Claude Code with a unique x-session-id header so every request from
# this terminal is taggable in ~/.claude/litellm-session-log.jsonl.
#
# Usage:
#   ./tools/claude-debug.sh                 # generates a fresh session id
#   SESSION_ID=foo ./tools/claude-debug.sh  # use an explicit id
#   ./tools/claude-debug.sh -- <claude args>
set -euo pipefail

if [[ -z "${SESSION_ID:-}" ]]; then
    if command -v uuidgen >/dev/null 2>&1; then
        SESSION_ID="$(uuidgen | tr -d '-' | cut -c1-8)"
    else
        SESSION_ID="$(date +%s)$RANDOM"
    fi
fi

export ANTHROPIC_CUSTOM_HEADERS="x-session-id: ${SESSION_ID}"

echo "[litellm-debug] session_id=${SESSION_ID}  (tail: python tools/litellm_recent.py --session ${SESSION_ID} --follow)" >&2

exec claude "$@"
