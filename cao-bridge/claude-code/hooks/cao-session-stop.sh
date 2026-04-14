#!/usr/bin/env bash
# CAO Bridge — Claude Code Stop hook
# Auto-reports session completion and pushes local skills to shared pool.
#
# Env: CAO_HUB_URL, CAO_STATE_FILE

set -euo pipefail

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
STATE_FILE="${CAO_STATE_FILE:-/tmp/cao-claude-state.json}"

# Read terminal_id from state file
if [ ! -f "$STATE_FILE" ]; then
  exit 0
fi

TID=$(grep -o '"terminal_id":"[^"]*"' "$STATE_FILE" 2>/dev/null | head -1 | cut -d'"' -f4)
if [ -z "$TID" ]; then
  exit 0
fi

# Report completion
curl -sf -X POST "${HUB}/remotes/${TID}/report" \
  -H "Content-Type: application/json" \
  -d '{"status":"completed","output":"Session ended."}' >/dev/null 2>&1 || true

# Push local skills to shared pool (if skill_sync is available)
SYNC_SCRIPT="$(dirname "$0")/../../skill_sync_cli.sh"
if [ -x "$SYNC_SCRIPT" ]; then
  "$SYNC_SCRIPT" push 2>/dev/null || true
fi

# Clean up state
rm -f "$STATE_FILE"
