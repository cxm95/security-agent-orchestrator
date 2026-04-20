#!/usr/bin/env python3
"""E2E test for CAO SDK lifecycle — validates bridge integration without requiring
the actual Claude Agent SDK or OpenCode SDK to be installed.

Tests:
1. CaoAgentLifecycle.start() → registers with Hub
2. CaoAgentLifecycle.build_context() → includes L1 index
3. CaoBridge.fetch_index() → returns index content
4. CaoAgentLifecycle.stop() → cleans up

Usage:
    # Hub must be running on 127.0.0.1:9889
    python test_sdk_lifecycle.py

    # Custom Hub URL
    CAO_HUB_URL=http://host:port python test_sdk_lifecycle.py
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure cao-bridge is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdk import CaoAgentLifecycle
from cao_bridge import CaoBridge


def test_bridge_fetch_index():
    """Test CaoBridge.fetch_index() against a running Hub."""
    hub = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889")
    bridge = CaoBridge(hub_url=hub)

    index = bridge.fetch_index()
    # Either empty (no notes) or contains content
    assert isinstance(index, str), f"Expected str, got {type(index)}"
    print(f"  ✅ fetch_index returned {len(index)} chars")
    if index:
        print(f"     Preview: {index[:100]}...")
    else:
        print("     (empty — no notes or no index yet)")
    return True


def test_lifecycle_start_stop():
    """Test lifecycle start → build_context → stop."""
    hub = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889")

    lifecycle = CaoAgentLifecycle(
        hub_url=hub,
        agent_profile="sdk-test",
        auto_cleanup=False,  # manual stop in test
    )

    # Start
    tid = lifecycle.start()
    assert tid, "Expected non-empty terminal_id"
    print(f"  ✅ start() → tid={tid}")

    # Build context
    ctx = lifecycle.build_context(include_kickoff=False)
    assert "[CAO]" in ctx, f"Context missing [CAO] prefix: {ctx[:50]}"
    assert f"Registered as {tid}" in ctx
    print(f"  ✅ build_context() → {len(ctx)} chars")

    # Check L1 index injection
    idx = lifecycle.fetch_index()
    if idx:
        assert "== Knowledge Index ==" in ctx, "L1 index should be in context"
        print(f"  ✅ L1 index injected ({len(idx)} chars)")
    else:
        assert "Knowledge Index" not in ctx, "Empty index should not appear in context"
        print(f"  ✅ No L1 index (expected — no notes)")

    # Stop
    lifecycle.stop()
    print(f"  ✅ stop() completed")
    return True


def test_lifecycle_reattach():
    """Test that a second start() reattaches using cached terminal_id."""
    hub = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889")

    lc1 = CaoAgentLifecycle(hub_url=hub, agent_profile="sdk-reattach-test", auto_cleanup=False)
    tid1 = lc1.start()
    lc1.stop()

    lc2 = CaoAgentLifecycle(hub_url=hub, agent_profile="sdk-reattach-test", auto_cleanup=False)
    tid2 = lc2.start()
    lc2.stop()

    # Should reattach to same terminal_id
    assert tid1 == tid2, f"Expected reattach: {tid1} != {tid2}"
    print(f"  ✅ reattach works: {tid1} == {tid2}")

    # Clean up state file
    sf = lc2._state_file()
    if sf.exists():
        sf.unlink()

    return True


def main():
    import requests

    hub = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889")

    # Check Hub availability
    print(f"Testing against Hub at {hub}")
    try:
        resp = requests.get(f"{hub}/health", timeout=5)
        resp.raise_for_status()
        print(f"  Hub is running ✅\n")
    except Exception as e:
        print(f"  ❌ Hub not reachable: {e}")
        print("  Start the Hub with: cao-server")
        sys.exit(1)

    tests = [
        ("CaoBridge.fetch_index()", test_bridge_fetch_index),
        ("CaoAgentLifecycle start/stop", test_lifecycle_start_stop),
        ("CaoAgentLifecycle reattach", test_lifecycle_reattach),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n─── {name} ───")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
