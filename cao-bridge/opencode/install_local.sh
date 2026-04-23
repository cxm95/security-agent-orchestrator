#!/usr/bin/env bash
# Install CAO Bridge in LOCAL_ONLY mode for OpenCode.
#
# One-shot setup: installs plugin + skills + MCP config + Python deps.
# After running this script, set CAO_LOCAL_ONLY=1 and start opencode.
#
# Usage:
#   ./install_local.sh              # Interactive (prompts for confirmation)
#   ./install_local.sh --yes        # Non-interactive (skip confirmations)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CAO_BRIDGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OC_CONFIG="$HOME/.config/opencode"
OC_JSON="$OC_CONFIG/opencode.json"
MCP_SCRIPT="$CAO_BRIDGE_DIR/cao_bridge_mcp.py"
AUTO_YES=0

[[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && AUTO_YES=1

confirm() {
  if [ "$AUTO_YES" = "1" ]; then return 0; fi
  read -rp "$1 [Y/n] " ans
  [[ -z "$ans" || "$ans" =~ ^[Yy] ]]
}

echo "============================================"
echo " CAO Bridge — Local-Only Mode Installer"
echo "============================================"
echo ""

# ── 1. Check prerequisites ──────────────────────────────────────────────
echo "[1/5] Checking prerequisites ..."
MISSING=0

if ! command -v opencode &>/dev/null; then
  echo "  ERROR: opencode not found. Install it first: https://opencode.ai"
  MISSING=1
else
  echo "  opencode $(opencode --version 2>/dev/null || echo '?')"
fi

if ! command -v git &>/dev/null; then
  echo "  ERROR: git not found."
  MISSING=1
else
  echo "  git $(git --version 2>/dev/null | head -1)"
fi

if ! command -v python3 &>/dev/null; then
  echo "  ERROR: python3 not found."
  MISSING=1
else
  echo "  python3 $(python3 --version 2>/dev/null | awk '{print $2}')"
fi

if [ "$MISSING" = "1" ]; then
  echo ""
  echo "Please install missing dependencies and re-run."
  exit 1
fi
echo ""

# ── 2. Install plugin + skills via install.sh ────────────────────────────
echo "[2/5] Installing plugin and skills ..."
bash "$SCRIPT_DIR/install.sh" --global
echo ""

# ── 3. Install Python dependencies ──────────────────────────────────────
echo "[3/5] Installing Python dependencies (fastmcp, requests) ..."
if python3 -c "import fastmcp, requests" 2>/dev/null; then
  echo "  Already installed."
else
  PIP_FLAGS=""
  # Detect system-managed Python (PEP 668)
  if python3 -c "import sysconfig; print(sysconfig.get_path('stdlib'))" 2>/dev/null | grep -q "/usr/lib"; then
    PIP_FLAGS="--break-system-packages"
  fi
  pip3 install $PIP_FLAGS fastmcp requests 2>&1 | tail -3
  echo "  Done."
fi
echo ""

# ── 4. Configure opencode.json ──────────────────────────────────────────
echo "[4/5] Configuring opencode.json ..."
mkdir -p "$OC_CONFIG"

if [ -f "$OC_JSON" ]; then
  # Merge MCP config into existing file
  python3 - "$OC_JSON" "$MCP_SCRIPT" <<'PY'
import json, sys

oc_json_path = sys.argv[1]
mcp_script = sys.argv[2]

with open(oc_json_path, "r", encoding="utf-8") as f:
    config = json.load(f)

# Ensure permission is set
if "permission" not in config:
    config["permission"] = "allow"

# Add/update MCP server config
mcp = config.setdefault("mcp", {})
mcp["cao-bridge"] = {
    "type": "local",
    "command": ["python3", mcp_script],
    "environment": {
        "CAO_LOCAL_ONLY": "1",
        "CAO_AGENT_PROFILE": "remote-opencode"
    }
}

with open(oc_json_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  Updated {oc_json_path}")
PY
else
  # Create new file
  python3 - "$OC_JSON" "$MCP_SCRIPT" <<'PY'
import json, sys

oc_json_path = sys.argv[1]
mcp_script = sys.argv[2]

config = {
    "$schema": "https://opencode.ai/config.json",
    "permission": "allow",
    "mcp": {
        "cao-bridge": {
            "type": "local",
            "command": ["python3", mcp_script],
            "environment": {
                "CAO_LOCAL_ONLY": "1",
                "CAO_AGENT_PROFILE": "remote-opencode"
            }
        }
    }
}

with open(oc_json_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  Created {oc_json_path}")
PY
fi
echo ""

# ── 5. Verify ────────────────────────────────────────────────────────────
echo "[5/5] Verifying installation ..."
OK=1

[ -f "$OC_CONFIG/plugins/cao-bridge.ts" ] && echo "  Plugin:     OK" || { echo "  Plugin:     MISSING"; OK=0; }
[ -d "$OC_CONFIG/skills/cao-build-l1-index" ] && echo "  L1 Skill:   OK" || { echo "  L1 Skill:   MISSING"; OK=0; }
[ -f "$OC_JSON" ] && echo "  Config:     OK" || { echo "  Config:     MISSING"; OK=0; }
python3 -c "import fastmcp" 2>/dev/null && echo "  fastmcp:    OK" || { echo "  fastmcp:    MISSING"; OK=0; }
python3 -c "import requests" 2>/dev/null && echo "  requests:   OK" || { echo "  requests:   MISSING"; OK=0; }
[ -f "$MCP_SCRIPT" ] && echo "  MCP Server: OK" || { echo "  MCP Server: MISSING ($MCP_SCRIPT)"; OK=0; }

echo ""
if [ "$OK" = "1" ]; then
  echo "============================================"
  echo " Installation complete!"
  echo "============================================"
  echo ""
  echo " To start opencode in local-only mode:"
  echo ""
  echo "   CAO_LOCAL_ONLY=1 opencode /path/to/project"
  echo ""
  echo " Or for headless HTTP server:"
  echo ""
  echo "   CAO_LOCAL_ONLY=1 opencode serve --port 19001"
  echo ""
  echo " To persist the env var, add to your shell profile:"
  echo ""
  echo "   echo 'export CAO_LOCAL_ONLY=1' >> ~/.bashrc"
  echo ""
  echo " See docs/USAGE_LOCAL.md for detailed usage guide."
  echo "============================================"
else
  echo "WARNING: Some components are missing. Check the output above."
  exit 1
fi
