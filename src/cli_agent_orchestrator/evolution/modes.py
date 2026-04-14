"""Runtime evolution modes: local, distributed, hybrid.

Controlled by the CAO_EVOLUTION_MODE environment variable.
Default is 'local' — no Hub needed, LLM-Judge + evals + structured retry.

Modes:
  local:       No Hub. Agent runs judge + evals locally. No sharing.
  distributed: Full Hub. grader + heartbeat + knowledge sharing + git sync.
  hybrid:      Local evolution + Hub sync for sharing results.

Each mode enables/disables specific subsystems via feature flags.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

VALID_MODES = ("local", "distributed", "hybrid")
DEFAULT_MODE = "local"


@dataclass(frozen=True)
class ModeConfig:
    """Feature flags derived from the evolution mode."""
    mode: str
    bridge_enabled: bool      # CAO Hub bridge (API sync)
    heartbeat_enabled: bool   # Hub-driven heartbeat checks
    grader_enabled: bool      # Remote grader integration
    judge_enabled: bool       # LLM-as-Judge local evaluation
    local_evolution: bool     # Local evolve_with_retry loop
    git_sync_enabled: bool    # Git remote push/pull


def get_mode() -> str:
    """Read evolution mode from environment."""
    mode = os.environ.get("CAO_EVOLUTION_MODE", DEFAULT_MODE).lower()
    if mode not in VALID_MODES:
        logger.warning("Unknown CAO_EVOLUTION_MODE=%s, falling back to %s", mode, DEFAULT_MODE)
        return DEFAULT_MODE
    return mode


def get_mode_config(mode: str | None = None) -> ModeConfig:
    """Get feature flags for the given (or current) mode."""
    if mode is None:
        mode = get_mode()

    if mode == "local":
        return ModeConfig(
            mode="local",
            bridge_enabled=False,
            heartbeat_enabled=False,
            grader_enabled=False,
            judge_enabled=True,
            local_evolution=True,
            git_sync_enabled=False,
        )
    elif mode == "distributed":
        return ModeConfig(
            mode="distributed",
            bridge_enabled=True,
            heartbeat_enabled=True,
            grader_enabled=True,
            judge_enabled=False,
            local_evolution=False,
            git_sync_enabled=True,
        )
    elif mode == "hybrid":
        return ModeConfig(
            mode="hybrid",
            bridge_enabled=True,
            heartbeat_enabled=True,
            grader_enabled=True,
            judge_enabled=True,
            local_evolution=True,
            git_sync_enabled=True,
        )
    else:
        return get_mode_config(DEFAULT_MODE)


def is_feature_enabled(feature: str, mode: str | None = None) -> bool:
    """Check if a specific feature is enabled in the current mode."""
    config = get_mode_config(mode)
    return getattr(config, feature, False)
