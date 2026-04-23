#!/usr/bin/env bash
# CAO Bridge — Claude Code Stop hook
# Auto-reports session completion, pushes local skills, and syncs git.
#
# The state file is kept on disk so the next SessionStart can reattach.
# Set CAO_CLEAR_STATE_ON_STOP=1 to force-remove it (e.g. in tests).
#
# Env: CAO_HUB_URL, CAO_STATE_FILE

set -euo pipefail

# Unified kill switch — set CAO_HOOKS_ENABLED=0 to disable all CAO hooks
if [ "${CAO_HOOKS_ENABLED:-1}" = "0" ]; then
  exit 0
fi

# TODO(local-only): add CAO_LOCAL_ONLY support — skip Hub report curl,
# keep skill mirror and git push to local bare repo.

# Bypass proxy for local Hub communication
export no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost"
export NO_PROXY="$no_proxy"

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
PROFILE="${CAO_AGENT_PROFILE:-remote-claude-code}"
CAO_CLIENT_BASE_DIR="${CAO_CLIENT_BASE_DIR:-$HOME/.cao-evolution-client}"
STATE_DIR="${CAO_CLIENT_BASE_DIR}/state"
STATE_FILE="${CAO_STATE_FILE:-$STATE_DIR/claude-code-${PROFILE}.json}"

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
  # Mirror local cao-* skills (e.g. evolved by secskill-evo into
  # ~/.claude/skills/cao-<name>/) into the clone before push. Non-prefixed
  # skills are private and never sync.
  LOCAL_SKILLS="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
  if [ -d "$LOCAL_SKILLS" ]; then
    mkdir -p "$SESSION_DIR/skills"
    for skill_dir in "$LOCAL_SKILLS"/cao-*/; do
      [ -d "$skill_dir" ] || continue
      [ -f "${skill_dir}SKILL.md" ] || continue
      name=$(basename "$skill_dir")
      rm -rf "$SESSION_DIR/skills/$name"
      cp -r "$skill_dir" "$SESSION_DIR/skills/$name" 2>/dev/null || true
    done
  fi

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

# Keep the state file by default so the next SessionStart hook can
# reattach to this terminal_id instead of registering anew.  If the
# Hub's remote_state row has been cleaned up meanwhile the reattach
# will 404 and register will take over.
if [ "${CAO_CLEAR_STATE_ON_STOP:-0}" = "1" ]; then
  rm -f "$STATE_FILE"
fi
