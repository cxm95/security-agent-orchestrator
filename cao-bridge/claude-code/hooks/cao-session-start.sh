#!/usr/bin/env bash
# CAO Bridge — Claude Code SessionStart hook
# Auto-syncs git repo, registers with Hub, and outputs shared knowledge as context.
#
# Configure in .claude/settings.local.json:
#   { "hooks": { "SessionStart": [{ "matcher":"", "hooks":[
#       {"type":"command","command":"/path/to/cao-session-start.sh"}]}]}}
#
# Env: CAO_HUB_URL, CAO_GIT_REMOTE, CAO_AGENT_PROFILE

set -euo pipefail

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
PROFILE="${CAO_AGENT_PROFILE:-remote-claude-code}"
STATE_FILE="${CAO_STATE_FILE:-/tmp/cao-claude-state-$$.json}"
GIT_REMOTE="${CAO_GIT_REMOTE:-}"

# ── Create session via session_manager ────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SESSION_DIR=""
if [ -n "$GIT_REMOTE" ]; then
  SESSION_DIR=$(_CAO_SCRIPT_DIR="$SCRIPT_DIR" _CAO_REMOTE="$GIT_REMOTE" _CAO_PROFILE="$PROFILE" python3 -c "
import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR'])
from session_manager import create_session
print(create_session(os.environ['_CAO_REMOTE'], agent_profile=os.environ['_CAO_PROFILE']))
" 2>/dev/null) || true

  # Pull shared skills into Claude's skill dir
  if [ -n "$SESSION_DIR" ]; then
    CLAUDE_SKILLS="$HOME/.claude/skills"
    SRC_SKILLS="$SESSION_DIR/skills"
    if [ -d "$SRC_SKILLS" ]; then
      mkdir -p "$CLAUDE_SKILLS"
      for skill_dir in "$SRC_SKILLS"/*/; do
        [ -f "${skill_dir}SKILL.md" ] || continue
        name=$(basename "$skill_dir")
        cp -r "$skill_dir" "$CLAUDE_SKILLS/$name" 2>/dev/null || true
      done
    fi
  fi
fi

# ── Register with Hub ─────────────────────────────────────────────────
REG=$(curl -sf -X POST "${HUB}/remotes/register" \
  -H "Content-Type: application/json" \
  -d "{\"agent_profile\":\"${PROFILE}\"}" 2>/dev/null) || {
  echo '{"context":"[CAO] Hub unreachable — running in standalone mode."}';
  exit 0;
}

TID=$(echo "$REG" | grep -o '"terminal_id":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -z "$TID" ]; then
  echo '{"context":"[CAO] Registration failed."}';
  exit 0;
fi

# Persist terminal_id and session_dir for stop hook
echo "{\"terminal_id\":\"${TID}\",\"session_dir\":\"${SESSION_DIR}\"}" > "$STATE_FILE"

# Fetch recent notes for context
NOTES=$(curl -sf "${HUB}/evolution/knowledge/notes" 2>/dev/null) || NOTES="[]"
NOTE_COUNT=$(echo "$NOTES" | grep -o '"filename"' | wc -l)

# Output context for Claude Code to ingest
cat <<EOF
{"context":"[CAO] Registered as ${TID}. ${NOTE_COUNT} shared knowledge notes available. Session dir: ${SESSION_DIR}. Use cao_poll to check for tasks, cao_search_knowledge to find relevant insights."}
EOF
