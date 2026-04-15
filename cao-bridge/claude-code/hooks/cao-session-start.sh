#!/usr/bin/env bash
# CAO Bridge — Claude Code SessionStart hook
# Auto-syncs git repo, registers with Hub, and outputs shared knowledge as context.
#
# Configure in .claude/settings.local.json:
#   { "hooks": { "SessionStart": [{ "matcher":"", "hooks":[
#       {"type":"command","command":"/path/to/cao-session-start.sh"}]}]}}
#
# Env: CAO_HUB_URL, CAO_GIT_REMOTE, CAO_CLIENT_DIR

set -euo pipefail

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
PROFILE="${CAO_AGENT_PROFILE:-remote-claude-code}"
STATE_FILE="${CAO_STATE_FILE:-/tmp/cao-claude-state.json}"
GIT_REMOTE="${CAO_GIT_REMOTE:-}"
CLIENT_DIR="${CAO_CLIENT_DIR:-$HOME/.cao-evolution-client}"

# ── Git sync (clone or pull) ──────────────────────────────────────────
if [ -n "$GIT_REMOTE" ]; then
  if [ -d "$CLIENT_DIR/.git" ]; then
    BRANCH=$(git -C "$CLIENT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    [ "$BRANCH" = "HEAD" ] && BRANCH="main"
    git -C "$CLIENT_DIR" fetch --all 2>/dev/null || true
    git -C "$CLIENT_DIR" pull --rebase origin "$BRANCH" 2>/dev/null || true
  else
    git clone --filter=blob:none "$GIT_REMOTE" "$CLIENT_DIR" 2>/dev/null || true
    if [ -d "$CLIENT_DIR/.git" ]; then
      git -C "$CLIENT_DIR" config user.name "cao-agent"
      git -C "$CLIENT_DIR" config user.email "cao-agent@local"
    fi
  fi

  # Pull shared skills into Claude's skill dir
  CLAUDE_SKILLS="$HOME/.claude/skills"
  SRC_SKILLS="$CLIENT_DIR/skills"
  if [ -d "$SRC_SKILLS" ]; then
    mkdir -p "$CLAUDE_SKILLS"
    for skill_dir in "$SRC_SKILLS"/*/; do
      [ -f "${skill_dir}SKILL.md" ] || continue
      name=$(basename "$skill_dir")
      cp -r "$skill_dir" "$CLAUDE_SKILLS/$name" 2>/dev/null || true
    done
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

# Persist terminal_id for stop hook
echo "{\"terminal_id\":\"${TID}\"}" > "$STATE_FILE"

# Fetch recent notes for context
NOTES=$(curl -sf "${HUB}/evolution/knowledge/notes" 2>/dev/null) || NOTES="[]"
NOTE_COUNT=$(echo "$NOTES" | grep -o '"filename"' | wc -l)

# Output context for Claude Code to ingest
cat <<EOF
{"context":"[CAO] Registered as ${TID}. ${NOTE_COUNT} shared knowledge notes available. Git sync: ${CLIENT_DIR}. Use cao_poll to check for tasks, cao_search_knowledge to find relevant insights."}
EOF
