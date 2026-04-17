#!/usr/bin/env bash
# CAO Bridge — Claude Code Stop hook
# Auto-reports session completion, pushes local skills, and syncs git.
#
# Env: CAO_HUB_URL, CAO_STATE_FILE

set -euo pipefail

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
STATE_FILE="${CAO_STATE_FILE:-/tmp/cao-claude-state-$$.json}"

# Read terminal_id from state file
if [ ! -f "$STATE_FILE" ]; then
  exit 0
fi

TID=$(grep -o '"terminal_id":"[^"]*"' "$STATE_FILE" 2>/dev/null | head -1 | cut -d'"' -f4)
SESSION_DIR=$(grep -o '"session_dir":"[^"]*"' "$STATE_FILE" 2>/dev/null | head -1 | cut -d'"' -f4)
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

# Push pending changes and deactivate session
if [ -n "$SESSION_DIR" ] && [ -d "$SESSION_DIR/.git" ]; then
  # Push pending changes
  BRANCH=$(git -C "$SESSION_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
  [ "$BRANCH" = "HEAD" ] && BRANCH="main"
  git -C "$SESSION_DIR" add -A 2>/dev/null || true
  git -C "$SESSION_DIR" diff --cached --quiet 2>/dev/null || \
    git -C "$SESSION_DIR" commit -m "[agent] session end" 2>/dev/null || true
  git -C "$SESSION_DIR" push origin "$BRANCH" 2>/dev/null || true
  # Deactivate session
  SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
  _CAO_SCRIPT_DIR="$SCRIPT_DIR" _CAO_SESSION_DIR="$SESSION_DIR" python3 -c "
import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR'])
from pathlib import Path
from session_manager import deactivate_session
deactivate_session(Path(os.environ['_CAO_SESSION_DIR']))
" 2>/dev/null || true
fi

# Clean up state
rm -f "$STATE_FILE"
