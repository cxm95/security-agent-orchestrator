#!/usr/bin/env bash
# CAO Bridge — Claude Code SessionStart hook
# Auto-syncs git repo, reattaches to (or registers with) Hub, and outputs
# shared knowledge as context.
#
# Configure in .claude/settings.local.json:
#   { "hooks": { "SessionStart": [{ "matcher":"", "hooks":[
#       {"type":"command","command":"/path/to/cao-session-start.sh"}]}]}}
#
# Env: CAO_HUB_URL, CAO_GIT_REMOTE, CAO_AGENT_PROFILE, CAO_STATE_FILE

set -euo pipefail

# Unified kill switch — set CAO_HOOKS_ENABLED=0 to disable all CAO hooks
if [ "${CAO_HOOKS_ENABLED:-1}" = "0" ]; then
  echo '{}'
  exit 0
fi

# Bypass proxy for local Hub communication
export no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost"
export NO_PROXY="$no_proxy"

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
PROFILE="${CAO_AGENT_PROFILE:-remote-claude-code}"
# Stable state path — lives under the same base dir as session metadata so
# terminal_id survives Claude Code restarts (old default used $$ which died
# with the PID and made reattach impossible).
CAO_CLIENT_BASE_DIR="${CAO_CLIENT_BASE_DIR:-$HOME/.cao-evolution-client}"
STATE_DIR="${CAO_CLIENT_BASE_DIR}/state"
mkdir -p "$STATE_DIR"
STATE_FILE="${CAO_STATE_FILE:-$STATE_DIR/claude-code-${PROFILE}.json}"
GIT_REMOTE="${CAO_GIT_REMOTE:-}"
# Disable the kickoff prompt (default: on) — set CAO_KICKOFF=0 to opt out.
KICKOFF="${CAO_KICKOFF:-1}"

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
        # Only sync shared-namespace skills (cao-* prefix) — leave private
        # local skills untouched.
        case "$name" in cao-*) ;; *) continue ;; esac
        cp -r "$skill_dir" "$CLAUDE_SKILLS/$name" 2>/dev/null || true
      done
    fi
  fi
fi

# ── Register with Hub ─────────────────────────────────────────────────
emit_plain_context() {
  # Emit a simple status-only context payload (no kickoff instruction).
  python3 - "$1" <<'PY'
import json, sys
ctx = sys.argv[1]
print(json.dumps({
    "context": ctx,
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    },
}))
PY
}

# ── Reattach-first: if the cached state file has a terminal_id, ask the
#     Hub whether it is still valid.  Only fall back to register when the
#     reattach call returns 404 (stale) or the cache is missing/corrupt.
TID=""
REATTACHED=0
CACHED_TID=""
if [ -f "$STATE_FILE" ]; then
  CACHED_TID=$(grep -o '"terminal_id":"[^"]*"' "$STATE_FILE" 2>/dev/null | head -1 | cut -d'"' -f4 || true)
fi

if [ -n "$CACHED_TID" ]; then
  RA_STATUS=$(curl -s -o /tmp/cao-reattach-$$.json -w "%{http_code}" -X POST \
    "${HUB}/remotes/${CACHED_TID}/reattach" 2>/dev/null || echo "000")
  if [ "$RA_STATUS" = "200" ]; then
    TID=$(grep -o '"terminal_id":"[^"]*"' /tmp/cao-reattach-$$.json 2>/dev/null | head -1 | cut -d'"' -f4 || true)
    [ -n "$TID" ] && REATTACHED=1
  fi
  rm -f /tmp/cao-reattach-$$.json
fi

if [ -z "$TID" ]; then
  REG=$(curl -sf -X POST "${HUB}/remotes/register" \
    -H "Content-Type: application/json" \
    -d "{\"agent_profile\":\"${PROFILE}\"}" 2>/dev/null) || {
    emit_plain_context "[CAO] Hub unreachable — running in standalone mode.";
    exit 0;
  }

  TID=$(echo "$REG" | grep -o '"terminal_id":"[^"]*"' | head -1 | cut -d'"' -f4)
  if [ -z "$TID" ]; then
    emit_plain_context "[CAO] Registration failed.";
    exit 0;
  fi
fi

# Persist terminal_id and session_dir at the stable path so the next
# restart of this agent can reattach instead of registering anew.
python3 - "$STATE_FILE" "$TID" "$SESSION_DIR" <<'PY'
import json, sys
path, tid, sdir = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "w", encoding="utf-8") as f:
    json.dump({"terminal_id": tid, "session_dir": sdir}, f)
PY

# Also mirror the terminal_id back into the session metadata so
# cao-bridge.py / MCP tools can see it without re-reading the state file.
if [ -n "$SESSION_DIR" ]; then
  _CAO_SCRIPT_DIR="$SCRIPT_DIR" _CAO_SESSION_DIR="$SESSION_DIR" _CAO_TID="$TID" python3 -c "
import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR'])
from pathlib import Path
from session_manager import set_terminal_id
set_terminal_id(Path(os.environ['_CAO_SESSION_DIR']), os.environ['_CAO_TID'])
" 2>/dev/null || true
fi

# Fetch recent notes for context.  ``grep -o`` returns 1 when there are no
# matches, which under ``set -euo pipefail`` would abort the whole script
# and produce empty output — guard with ``|| true``.
NOTES=$(curl -sf "${HUB}/evolution/knowledge/notes" 2>/dev/null) || NOTES="[]"
NOTE_COUNT=$(echo "$NOTES" | grep -o '"filename"' | wc -l || true)
NOTE_COUNT="${NOTE_COUNT:-0}"

# Fetch L1 knowledge index (generated by Root Orchestrator).
# Push-only mode (default) skips the pull — set CAO_PUSH_ONLY=0 to re-enable.
if [ "${CAO_PUSH_ONLY:-1}" = "0" ]; then
  L1_INDEX=$(curl -sf "${HUB}/evolution/index" 2>/dev/null) || L1_INDEX=""
else
  L1_INDEX=""
fi

# Compose the additional context. When KICKOFF=1, instruct Claude to call
# ``cao_poll`` as the very first action — this is how Claude Code–derived
# CLIs kick off the active-polling loop (the Stop hook keeps it going).
KICKOFF_INSTRUCTION=""
if [ "$KICKOFF" = "1" ]; then
  KICKOFF_INSTRUCTION=" Your first action in this session MUST be to call the cao_poll MCP tool to check for queued tasks; if has_input is true, execute the returned task. Do not wait for a user message — call cao_poll immediately."
fi

REATTACH_TAG=""
if [ "$REATTACHED" = "1" ]; then
  REATTACH_TAG=" (reattached)"
fi

CTX="[CAO] Registered as ${TID}${REATTACH_TAG}. ${NOTE_COUNT} shared knowledge notes available. Session dir: ${SESSION_DIR}. Use cao_poll to check for tasks, cao_search_knowledge to find relevant insights.${KICKOFF_INSTRUCTION}"

# Append L1 knowledge index if available (skip default placeholder)
if [ -n "$L1_INDEX" ] && ! echo "$L1_INDEX" | grep -q "No index available yet"; then
  CTX="${CTX}

== Knowledge Index ==
${L1_INDEX}
== End Knowledge Index =="
fi

# Output context for Claude Code to ingest.  ``additionalContext`` under
# ``hookSpecificOutput`` is the modern SessionStart payload; the legacy
# top-level ``context`` key is kept for backward compatibility with older
# Claude Code builds that haven't picked up the newer schema.
python3 - "$CTX" <<'PY'
import json, sys
ctx = sys.argv[1]
print(json.dumps({
    "context": ctx,
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    },
}))
PY
