#!/usr/bin/env bash
# CAO Bridge — Claude Code SessionStart hook
# Auto-registers with Hub and outputs shared knowledge as context.
#
# Configure in .claude/settings.local.json:
#   { "hooks": { "SessionStart": [{ "matcher":"", "hooks":[
#       {"type":"command","command":"/path/to/cao-session-start.sh"}]}]}}
#
# Env: CAO_HUB_URL (default http://127.0.0.1:9889)

set -euo pipefail

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
PROFILE="${CAO_AGENT_PROFILE:-remote-claude-code}"
STATE_FILE="${CAO_STATE_FILE:-/tmp/cao-claude-state.json}"

# Register with Hub
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

# Persist terminal_id for stop hook
echo "{\"terminal_id\":\"${TID}\"}" > "$STATE_FILE"

# Fetch recent notes for context
NOTES=$(curl -sf "${HUB}/evolution/knowledge/notes" 2>/dev/null) || NOTES="[]"
NOTE_COUNT=$(echo "$NOTES" | grep -o '"filename"' | wc -l)

# Output context for Claude Code to ingest
cat <<EOF
{"context":"[CAO] Registered as ${TID}. ${NOTE_COUNT} shared knowledge notes available. Use cao_poll to check for tasks, cao_search_knowledge to find relevant insights."}
EOF
