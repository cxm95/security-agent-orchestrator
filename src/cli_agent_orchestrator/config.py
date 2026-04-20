"""YAML-based configuration for CAO Hub.

Reads ``~/.aws/cli-agent-orchestrator/config.yaml`` (or ``CAO_CONFIG``
env-var override).  Missing file → all defaults.

Example config.yaml:

    root_orchestrator:
      enabled: true
      provider: clother_closeai
      profile: root_orchestrator
      session: ROOT
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml

from cli_agent_orchestrator.constants import CAO_HOME_DIR

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(os.environ.get("CAO_CONFIG", str(CAO_HOME_DIR / "config.yaml")))


@dataclass
class RootOrchestratorConfig:
    enabled: bool = True
    provider: str = "clother_closeai"
    profile: str = "root_orchestrator"
    session: str = "ROOT"


@dataclass
class CaoConfig:
    root_orchestrator: RootOrchestratorConfig = field(default_factory=RootOrchestratorConfig)


def load_config() -> CaoConfig:
    """Load config from YAML file.  Returns defaults when file is absent or invalid."""
    cfg = CaoConfig()
    if not _CONFIG_PATH.exists():
        logger.debug("No config file at %s — using defaults", _CONFIG_PATH)
        return cfg

    try:
        raw: Dict[str, Any] = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    except Exception as e:
        logger.warning("Failed to parse %s: %s — using defaults", _CONFIG_PATH, e)
        return cfg

    ro = raw.get("root_orchestrator")
    if isinstance(ro, dict):
        cfg.root_orchestrator = RootOrchestratorConfig(
            enabled=ro.get("enabled", cfg.root_orchestrator.enabled),
            provider=ro.get("provider", cfg.root_orchestrator.provider),
            profile=ro.get("profile", cfg.root_orchestrator.profile),
            session=ro.get("session", cfg.root_orchestrator.session),
        )

    return cfg
