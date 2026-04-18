#!/usr/bin/env bash
# Install CAO Bridge for OpenCode.
#
# Usage:
#   ./install.sh                    # Default: global install
#   ./install.sh --global           # Same as above (explicit)
#   ./install.sh --project [dir]    # Project-level install
#
# Global install writes to:
#   ~/.config/opencode/plugins/cao-bridge.ts  — CAO Bridge plugin
#   ~/.config/opencode/skills/*/SKILL.md      — Remote skills (if any)
#
# Existing files are backed up as <file>.bak.<timestamp> before overwriting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CAO_BRIDGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$CAO_BRIDGE_DIR/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"

PLUGIN_SRC="$CAO_BRIDGE_DIR/plugin/cao-bridge.ts"
SKILLS_SRC="$REPO_ROOT/experiment/skill_to_install_remote"

# ── Helpers ──────────────────────────────────────────────────────────────

backup_if_exists() {
  local file="$1"
  if [ -f "$file" ]; then
    local bak="${file}.bak.${TIMESTAMP}"
    cp "$file" "$bak"
    echo "  Backed up $file → $bak"
  fi
}

install_plugin() {
  local dst_dir="$1"
  mkdir -p "$dst_dir"
  local dst="$dst_dir/cao-bridge.ts"
  backup_if_exists "$dst"
  cp "$PLUGIN_SRC" "$dst"
  echo "  Installed plugin → $dst"
}

install_skills() {
  local dst_dir="$1"
  if [ ! -d "$SKILLS_SRC" ]; then
    echo "  No remote skills found at $SKILLS_SRC — skipping"
    return
  fi
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -d "$skill_dir" ] || continue
    local skill_name
    skill_name="$(basename "$skill_dir")"
    local dst="$dst_dir/$skill_name"
    mkdir -p "$dst"
    cp -r "$skill_dir"* "$dst/"
    echo "  Installed skill: $skill_name → $dst"
  done
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
      MODE="project"; TARGET="$1"; shift ;;
  esac
done

# ── Global install ───────────────────────────────────────────────────────

if [ "$MODE" = "global" ]; then
  echo "Installing CAO Bridge for OpenCode (global) ..."

  OC_CONFIG="$HOME/.config/opencode"

  # 1. Plugin
  install_plugin "$OC_CONFIG/plugins"

  # 2. Skills
  install_skills "$OC_CONFIG/skills"

  # 3. Check permission config
  OC_JSON="$OC_CONFIG/opencode.json"
  if [ -f "$OC_JSON" ]; then
    if grep -q '"permission"' "$OC_JSON" 2>/dev/null; then
      echo "  Permission config found in $OC_JSON"
    else
      echo "  WARNING: $OC_JSON exists but has no \"permission\" field."
      echo "  Add '\"permission\": \"allow\"' for auto-approval."
    fi
  else
    echo "  WARNING: $OC_JSON not found. Create it with:"
    echo '  echo '\''{"permission": "allow"}'\'' > '"$OC_JSON"
  fi

  echo ""
  echo "Done! CAO Bridge installed globally for OpenCode."
  exit 0
fi

# ── Project-level install ────────────────────────────────────────────────

TARGET="${TARGET:-.}"
TARGET="$(cd "$TARGET" && pwd)"

echo "Installing CAO Bridge for OpenCode in: $TARGET"

# Plugin → project .opencode/plugins/
install_plugin "$TARGET/.opencode/plugins"

# Skills → project .opencode/skills/
install_skills "$TARGET/.opencode/skills"

echo ""
echo "Done! Start OpenCode in $TARGET to use CAO Bridge."
