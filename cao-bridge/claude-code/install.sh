#!/usr/bin/env bash
# Install CAO Bridge for Claude Code.
#
# Usage:
#   ./install.sh                    # Default: global install (~/.claude/)
#   ./install.sh --global           # Same as above (explicit)
#   ./install.sh --project [dir]    # Project-level install (original behavior)
#
# Global install writes to:
#   ~/.claude.json              — MCP server (user scope)
#   ~/.claude/settings.local.json — Hooks (SessionStart, Stop, SessionEnd)
#   ~/.claude/CLAUDE.md         — CAO protocol instructions
#   ~/.claude/commands/evolve.md — /evolve slash command
#
# Existing files are backed up as <file>.bak.<timestamp> before overwriting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CAO_BRIDGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"

# ── Helpers ──────────────────────────────────────────────────────────────

backup_if_exists() {
  local file="$1"
  if [ -f "$file" ]; then
    local bak="${file}.bak.${TIMESTAMP}"
    cp "$file" "$bak"
    echo "  Backed up $file → $bak"
  fi
}

# ── Parse arguments ──────────────────────────────────────────────────────

MODE="global"
TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --global)
      MODE="global"; shift ;;
    --project)
      MODE="project"
      if [[ $# -gt 1 && ! "$2" =~ ^-- ]]; then
        TARGET="$2"; shift 2
      else
        TARGET="."; shift
      fi
      ;;
    *)
      # Positional arg (legacy compat): treat as project dir
      MODE="project"; TARGET="$1"; shift ;;
  esac
done

# ── Global install ───────────────────────────────────────────────────────

if [ "$MODE" = "global" ]; then
  echo "Installing CAO Bridge for Claude Code (global) ..."

  MCP_PY="$CAO_BRIDGE_DIR/cao_bridge_mcp.py"
  START_HOOK="$SCRIPT_DIR/hooks/cao-session-start.sh"
  GRADER_HOOK="$SCRIPT_DIR/hooks/cao-stop-grader.py"
  END_HOOK="$SCRIPT_DIR/hooks/cao-session-stop.sh"
  chmod +x "$START_HOOK" "$END_HOOK"

  # 1. MCP server → ~/.claude.json (user scope)
  CLAUDE_JSON="$HOME/.claude.json"
  backup_if_exists "$CLAUDE_JSON"
  cat > "$CLAUDE_JSON" <<EOF
{
  "user": {
    "mcpServers": {
      "cao-bridge": {
        "command": "python3",
        "args": ["$MCP_PY"],
        "env": {
          "CAO_HUB_URL": "${CAO_HUB_URL:-http://127.0.0.1:9889}",
          "CAO_AGENT_PROFILE": "remote-claude-code",
          "CAO_GIT_REMOTE": "${CAO_GIT_REMOTE:-}",
          "CAO_CLIENT_DIR": "${CAO_CLIENT_DIR:-$HOME/.cao-evolution-client}",
          "no_proxy": "127.0.0.1,localhost",
          "NO_PROXY": "127.0.0.1,localhost"
        }
      }
    }
  }
}
EOF
  echo "  Installed MCP config → $CLAUDE_JSON"

  # 2. Hooks → ~/.claude/settings.local.json
  mkdir -p "$HOME/.claude"
  SETTINGS="$HOME/.claude/settings.local.json"
  backup_if_exists "$SETTINGS"
  cat > "$SETTINGS" <<EOF
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "$START_HOOK"}]
    }],
    "Stop": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "python3 $GRADER_HOOK"}]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "$END_HOOK"}]
    }]
  }
}
EOF
  echo "  Installed hooks → $SETTINGS"

  # 3. CLAUDE.md → ~/.claude/CLAUDE.md
  CLAUDE_MD_DST="$HOME/.claude/CLAUDE.md"
  backup_if_exists "$CLAUDE_MD_DST"
  cp "$SCRIPT_DIR/CLAUDE.md" "$CLAUDE_MD_DST"
  echo "  Installed CLAUDE.md → $CLAUDE_MD_DST"

  # 4. /evolve command → ~/.claude/commands/evolve.md
  mkdir -p "$HOME/.claude/commands"
  cp "$SCRIPT_DIR/commands/evolve.md" "$HOME/.claude/commands/evolve.md"
  echo "  Installed /evolve command → ~/.claude/commands/evolve.md"

  echo ""
  echo "Done! CAO Bridge installed globally for Claude Code."
  echo "  MCP tools: cao_register, cao_poll, cao_report, cao_report_score, ..."
  echo "  Command:   /evolve — trigger evolution cycle"
  echo "  Hooks:     SessionStart (register), Stop (auto-grading), SessionEnd (cleanup)"
  exit 0
fi

# ── Project-level install (original behavior) ────────────────────────────

TARGET="${TARGET:-.}"
TARGET="$(cd "$TARGET" && pwd)"

echo "Installing CAO Bridge for Claude Code in: $TARGET"

# 1. Create directory structure
mkdir -p "$TARGET/.claude/commands"

# 2. Copy CLAUDE.md to project root
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
        "CAO_GIT_REMOTE": "${CAO_GIT_REMOTE:-}",
        "CAO_CLIENT_DIR": "${CAO_CLIENT_DIR:-$HOME/.cao-evolution-client}",
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
GRADER_HOOK="$SCRIPT_DIR/hooks/cao-stop-grader.py"
END_HOOK="$SCRIPT_DIR/hooks/cao-session-stop.sh"
chmod +x "$START_HOOK" "$END_HOOK"

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
      "hooks": [{"type": "command", "command": "python3 $GRADER_HOOK"}]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "$END_HOOK"}]
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
  echo "    Stop: python3 $GRADER_HOOK"
fi

echo ""
echo "Done! Start Claude Code in $TARGET to use CAO Bridge."
echo "  MCP tools: cao_register, cao_poll, cao_report, cao_report_score, ..."
echo "  Command:   /evolve — trigger evolution cycle"
echo "  Hooks:     SessionStart (register), Stop (auto-grading), SessionEnd (cleanup)"
