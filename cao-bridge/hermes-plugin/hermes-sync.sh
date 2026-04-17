#!/bin/bash
# hermes-sync.sh — Fallback sync script (no Plugin required).
# Pushes hermes skills + MEMORY.md entries to CAO Hub via HTTP API,
# then does git pull to sync latest shared knowledge locally.
#
# Usage:
#   ./hermes-sync.sh              # one-shot
#   watch -n 60 ./hermes-sync.sh  # periodic (every 60s)
#
# Environment:
#   CAO_HUB_URL       — Hub URL (default: http://127.0.0.1:9889)
#   HERMES_HOME       — Hermes home dir (default: ~/.hermes)
#   CAO_AGENT_PROFILE — Agent profile (default: remote-hermes)
#   CAO_GIT_REMOTE    — Git remote URL for evolution repo
#   CAO_CLIENT_DIR    — Override session dir (skips session_manager)
set -euo pipefail

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
HERMES="${HERMES_HOME:-$HOME/.hermes}"
PROFILE="${CAO_AGENT_PROFILE:-remote-hermes}"
GIT_REMOTE="${CAO_GIT_REMOTE:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PUSHED=0

# ── Session init (creates isolated session dir with git clone) ────────
SESSION_DIR="${CAO_CLIENT_DIR:-}"
if [ -z "$SESSION_DIR" ] && [ -n "$GIT_REMOTE" ]; then
  SESSION_DIR=$(_CAO_SCRIPT_DIR="$SCRIPT_DIR" _CAO_REMOTE="$GIT_REMOTE" _CAO_PROFILE="$PROFILE" python3 -c "
import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR'])
from session_manager import create_session
print(create_session(os.environ['_CAO_REMOTE'], agent_profile=os.environ['_CAO_PROFILE']))
" 2>/dev/null) || true
  if [ -n "$SESSION_DIR" ]; then
    echo "[hermes-sync] Session created: $SESSION_DIR"
  else
    echo "[hermes-sync] Session init failed, falling back to legacy mode" >&2
    SESSION_DIR="$HOME/.cao-evolution-client"
  fi
elif [ -z "$SESSION_DIR" ]; then
  SESSION_DIR="$HOME/.cao-evolution-client"
fi

# Pull shared skills into hermes local dir
SRC_SKILLS="$SESSION_DIR/skills"
HERMES_SKILLS="$HERMES/skills"
if [ -d "$SRC_SKILLS" ]; then
  mkdir -p "$HERMES_SKILLS"
  for skill_dir in "$SRC_SKILLS"/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name=$(basename "$skill_dir")
    cp -r "$skill_dir" "$HERMES_SKILLS/$name" 2>/dev/null || true
  done
  echo "[hermes-sync] Pulled shared skills from git clone"
fi

# Register (get terminal_id)
TID=$(curl -sf -X POST "$HUB/remotes/register" \
    -H "Content-Type: application/json" \
    -d "{\"agent_profile\":\"$PROFILE\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['terminal_id'])" 2>/dev/null) || {
    echo "[hermes-sync] Failed to register with Hub at $HUB" >&2
    exit 1
}
echo "[hermes-sync] Registered: terminal_id=$TID"

# Push skills
if [ -d "$HERMES/skills" ]; then
    for skill_dir in "$HERMES/skills"/*/; do
        [ -d "$skill_dir" ] || continue
        name=$(basename "$skill_dir")
        skill_md="$skill_dir/SKILL.md"
        [ -f "$skill_md" ] || continue

        content=$(cat "$skill_md")
        # JSON-escape the content
        json_content=$(python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" <<< "$content")

        curl -sf -X POST "$HUB/evolution/knowledge/skills" \
            -H "Content-Type: application/json" \
            -d "{\"name\":\"$name\",\"content\":$json_content,\"tags\":[\"hermes\",\"$name\"],\"agent_id\":\"$TID\"}" >/dev/null && {
            PUSHED=$((PUSHED + 1))
            echo "[hermes-sync] Pushed skill: $name"
        }
    done
fi

# Push MEMORY.md entries
MEMORY_FILE="$HERMES/memories/MEMORY.md"
if [ -f "$MEMORY_FILE" ]; then
    python3 -c "
import hashlib, json, re, sys
import urllib.request

hub = '$HUB'
tid = '$TID'
mem = open('$MEMORY_FILE', encoding='utf-8', errors='replace').read()
# Skip header lines
mem = re.sub(r'^═.*$', '', mem, flags=re.MULTILINE)
mem = re.sub(r'^MEMORY\s*\(.*?\)\s*\[.*?\]\s*$', '', mem, flags=re.MULTILINE)
pushed = 0
for entry in mem.split('§'):
    entry = entry.strip()
    if not entry:
        continue
    digest = hashlib.sha256(entry.encode()).hexdigest()[:12]
    title = f'hermes-memory-{digest}'
    data = json.dumps({
        'title': title, 'content': entry,
        'tags': ['hermes', 'memory'], 'agent_id': tid,
    }).encode()
    req = urllib.request.Request(
        f'{hub}/evolution/knowledge/notes',
        data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        urllib.request.urlopen(req, timeout=10)
        pushed += 1
    except Exception as e:
        print(f'[hermes-sync] Failed to push note {title}: {e}', file=sys.stderr)
print(f'[hermes-sync] Pushed {pushed} memory entries')
"
fi

echo "[hermes-sync] Done. Skills pushed: $PUSHED"

# Final git pull to pick up our HTTP writes + others' changes
if [ -d "$SESSION_DIR/.git" ]; then
  BRANCH=$(git -C "$SESSION_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
  [ "$BRANCH" = "HEAD" ] && BRANCH="main"
  git -C "$SESSION_DIR" pull --rebase origin "$BRANCH" 2>/dev/null || true
  echo "[hermes-sync] Final git pull done"
fi

# Deactivate session (one-shot mode)
if [ -z "${CAO_CLIENT_DIR:-}" ] && [ -n "$GIT_REMOTE" ] && [ -n "$SESSION_DIR" ]; then
  _CAO_SCRIPT_DIR="$SCRIPT_DIR" _CAO_SESSION_DIR="$SESSION_DIR" python3 -c "
import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR'])
from pathlib import Path
from session_manager import deactivate_session
deactivate_session(Path(os.environ['_CAO_SESSION_DIR']))
" 2>/dev/null || true
fi
