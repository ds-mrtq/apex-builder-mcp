# src/apex_builder_mcp/guard/env_guard.py
from __future__ import annotations

from enum import Enum, auto
from typing import Literal


class PolicyDecision(Enum):
    EXECUTE = auto()
    DRY_RUN_ONLY = auto()
    REJECT = auto()


class EnvGuardError(ValueError):
    """Raised on unknown environment."""


def decide_write_action(
    environment: Literal["DEV", "TEST", "PROD"],
    tool_name: str,
    is_destructive: bool,
    block_destructive: bool = False,
) -> PolicyDecision:
    if environment not in ("DEV", "TEST", "PROD"):
        raise EnvGuardError(f"Unknown environment: {environment!r}")

    if environment == "PROD":
        return PolicyDecision.REJECT
    if environment == "TEST":
        return PolicyDecision.DRY_RUN_ONLY
    # DEV
    if is_destructive and block_destructive:
        return PolicyDecision.REJECT
    return PolicyDecision.EXECUTE
