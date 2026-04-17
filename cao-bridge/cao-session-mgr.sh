#!/usr/bin/env bash
# cao-session-mgr — Manage agent session directories.
#
# Usage:
#   cao-session-mgr create [--git-remote URL] [--profile NAME]
#   cao-session-mgr list [--status active|inactive]
#   cao-session-mgr cleanup [--max-age HOURS]
#   cao-session-mgr info SESSION_ID
#
# Environment:
#   CAO_GIT_REMOTE      — Git remote URL for the evolution repo
#   CAO_CLIENT_BASE_DIR — Base directory (default: ~/.cao-evolution-client)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

_py() {
  _CAO_SCRIPT_DIR="$SCRIPT_DIR" python3 -c "
import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR'])
$1
"
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  create)
    GIT_REMOTE="${CAO_GIT_REMOTE:-}"
    PROFILE=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --git-remote) GIT_REMOTE="$2"; shift 2 ;;
        --profile)    PROFILE="$2"; shift 2 ;;
        *)            echo "Unknown option: $1" >&2; exit 1 ;;
      esac
    done
    if [ -z "$GIT_REMOTE" ]; then
      echo "Error: --git-remote or CAO_GIT_REMOTE required" >&2
      exit 1
    fi
    export _CAO_ARG_REMOTE="$GIT_REMOTE"
    export _CAO_ARG_PROFILE="$PROFILE"
    _py "
import os
from session_manager import create_session
sdir = create_session(os.environ['_CAO_ARG_REMOTE'], agent_profile=os.environ.get('_CAO_ARG_PROFILE', ''))
print(sdir)
"
    ;;

  list)
    STATUS=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --status) STATUS="$2"; shift 2 ;;
        *)        echo "Unknown option: $1" >&2; exit 1 ;;
      esac
    done
    export _CAO_ARG_STATUS="$STATUS"
    _py "
import os
from session_manager import list_sessions
status = os.environ.get('_CAO_ARG_STATUS') or None
sessions = list_sessions(status=status)
for s in sessions:
    sid = s.get('session_id', '?')
    st = s.get('status', '?')
    lu = s.get('last_update', '?')
    prof = s.get('agent_profile', '')
    print(f'{sid}  {st:10s}  {lu}  {prof}')
if not sessions:
    print('No sessions found.')
"
    ;;

  cleanup)
    MAX_AGE=24
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --max-age) MAX_AGE="$2"; shift 2 ;;
        *)         echo "Unknown option: $1" >&2; exit 1 ;;
      esac
    done
    export _CAO_ARG_MAX_AGE="$MAX_AGE"
    _py "
import os
from session_manager import cleanup_sessions
removed = cleanup_sessions(max_age_hours=int(os.environ['_CAO_ARG_MAX_AGE']))
if removed:
    for sid in removed:
        print(f'Removed: {sid}')
    print(f'{len(removed)} session(s) cleaned up.')
else:
    print('No sessions to clean up.')
"
    ;;

  info)
    SID="${1:-}"
    if [ -z "$SID" ]; then
      echo "Usage: cao-session-mgr info SESSION_ID" >&2
      exit 1
    fi
    export _CAO_ARG_SID="$SID"
    _py "
import json, os
from session_manager import get_session_dir, _read_meta
sid = os.environ['_CAO_ARG_SID']
sdir = get_session_dir(sid)
meta = _read_meta(sdir)
if meta:
    print(json.dumps(meta, indent=2))
else:
    print(f'Session not found: {sid}', file=__import__('sys').stderr)
    exit(1)
"
    ;;

  help|--help|-h)
    echo "Usage: cao-session-mgr {create|list|cleanup|info} [options]"
    echo ""
    echo "Commands:"
    echo "  create   Create a new session directory (git clone)"
    echo "  list     List all sessions"
    echo "  cleanup  Remove expired inactive sessions"
    echo "  info     Show session metadata"
    ;;

  *)
    echo "Unknown command: $cmd" >&2
    echo "Run 'cao-session-mgr help' for usage." >&2
    exit 1
    ;;
esac
