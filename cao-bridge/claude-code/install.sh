#!/usr/bin/env bash
# Install CAO Bridge for Claude Code.
#
# Creates the .claude/ directory structure in the target project and
# configures MCP + hooks + commands.
#
# Usage:
#   ./install.sh [target_project_dir]
#
# If target_project_dir is omitted, installs to current directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CAO_BRIDGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET="${1:-.}"
TARGET="$(cd "$TARGET" && pwd)"

echo "Installing CAO Bridge for Claude Code in: $TARGET"

# 1. Create directory structure
mkdir -p "$TARGET/.claude/commands"

# 2. Copy CLAUDE.md to project root (if not present)
if [ ! -f "$TARGET/CLAUDE.md" ]; then
  cp "$SCRIPT_DIR/CLAUDE.md" "$TARGET/CLAUDE.md"
  echo "  Created CLAUDE.md"
else
  echo "  CLAUDE.md already exists — skipping (merge manually if needed)"
fi

# 3. Install .mcp.json with correct path to cao_bridge_mcp.py
MCP_PY="$CAO_BRIDGE_DIR/cao_bridge_mcp.py"
cat > "$TARGET/.mcp.json" <<EOF
{
  "mcpServers": {
    "cao-bridge": {
      "command": "python3",
      "args": ["$MCP_PY"],
      "env": {
        "CAO_HUB_URL": "${CAO_HUB_URL:-http://127.0.0.1:9889}",
        "CAO_AGENT_PROFILE": "remote-claude-code",
        "no_proxy": "127.0.0.1,localhost",
        "NO_PROXY": "127.0.0.1,localhost"
      }
    }
  }
}
EOF
echo "  Created .mcp.json → $MCP_PY"

# 4. Install /evolve command
cp "$SCRIPT_DIR/commands/evolve.md" "$TARGET/.claude/commands/evolve.md"
echo "  Created .claude/commands/evolve.md"

# 5. Install hooks
START_HOOK="$SCRIPT_DIR/hooks/cao-session-start.sh"
STOP_HOOK="$SCRIPT_DIR/hooks/cao-session-stop.sh"
chmod +x "$START_HOOK" "$STOP_HOOK"

# Create or merge settings.local.json with hook config
SETTINGS="$TARGET/.claude/settings.local.json"
HOOKS_JSON=$(cat <<EOF
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "$START_HOOK"}]
    }],
    "Stop": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "$STOP_HOOK"}]
    }]
  }
}
EOF
)

if [ ! -f "$SETTINGS" ]; then
  echo "$HOOKS_JSON" > "$SETTINGS"
  echo "  Created .claude/settings.local.json with hooks"
else
  echo "  .claude/settings.local.json exists — add hooks manually:"
  echo "    SessionStart: $START_HOOK"
  echo "    Stop: $STOP_HOOK"
fi

echo ""
echo "Done! Start Claude Code in $TARGET to use CAO Bridge."
echo "  MCP tools: cao_register, cao_poll, cao_report, cao_report_score, ..."
echo "  Command:   /evolve — trigger evolution cycle"
echo "  Hooks:     auto-register on start, auto-report on stop"
