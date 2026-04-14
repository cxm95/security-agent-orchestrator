#!/bin/bash
# hermes-sync.sh — Fallback sync script (no Plugin required).
# Pushes hermes skills + MEMORY.md entries to CAO Hub via HTTP API.
# Same data path as the Plugin: CaoBridge → HTTP → files → git.
#
# Usage:
#   ./hermes-sync.sh              # one-shot
#   watch -n 60 ./hermes-sync.sh  # periodic (every 60s)
#
# Environment:
#   CAO_HUB_URL      — Hub URL (default: http://127.0.0.1:9889)
#   HERMES_HOME       — Hermes home dir (default: ~/.hermes)
#   CAO_AGENT_PROFILE — Agent profile (default: remote-hermes)
set -euo pipefail

HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
HERMES="${HERMES_HOME:-$HOME/.hermes}"
PROFILE="${CAO_AGENT_PROFILE:-remote-hermes}"
PUSHED=0

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
