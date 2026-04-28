# src/apex_builder_mcp/connection/state.py
from __future__ import annotations

from typing import Literal

from apex_builder_mcp.schema.profile import Profile

Status = Literal[
    "UNCONFIGURED",
    "CONFIGURED",
    "CONNECTED:DEV",
    "CONNECTED:TEST",
    "CONNECTED:PROD",
    "DISCONNECTED",
]


class ConnectionState:
    """Single source of truth for current MCP session state."""

    def __init__(self) -> None:
        self._profile: Profile | None = None
        self._connected: bool = False
        self._disconnected_explicitly: bool = False

    @property
    def profile(self) -> Profile | None:
        return self._profile

    @property
    def status(self) -> Status:
        if self._disconnected_explicitly:
            return "DISCONNECTED"
        if self._profile is None:
            return "UNCONFIGURED"
        if not self._connected:
            return "CONFIGURED"
        return f"CONNECTED:{self._profile.environment}"  # type: ignore[return-value]

    def set_profile(self, profile: Profile) -> None:
        self._profile = profile
        self._connected = False
        self._disconnected_explicitly = False

    def mark_connected(self) -> None:
        if self._profile is None:
            raise RuntimeError("Cannot mark connected without profile")
        self._connected = True
        self._disconnected_explicitly = False

    def mark_disconnected(self) -> None:
        self._connected = False
        self._disconnected_explicitly = True


# module-level singleton accessor
_state: ConnectionState | None = None


def get_state() -> ConnectionState:
    global _state
    if _state is None:
        _state = ConnectionState()
    return _state


def reset_state_for_tests() -> None:
    """Test-only: clear singleton so tests don't bleed."""
    global _state
    _state = None
