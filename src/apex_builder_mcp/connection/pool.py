# src/apex_builder_mcp/connection/pool.py
from __future__ import annotations

import os
from typing import Literal

import oracledb

from apex_builder_mcp.schema.profile import Profile

# Default TCP connect timeout for oracledb. Without this, a wrong DSN or
# firewalled host can stall the MCP server for minutes. Override with
# APEX_BUILDER_TCP_CONNECT_TIMEOUT_SEC.
DEFAULT_TCP_CONNECT_TIMEOUT_SEC = 10


def _tcp_connect_timeout_sec() -> int:
    raw = os.environ.get("APEX_BUILDER_TCP_CONNECT_TIMEOUT_SEC")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_TCP_CONNECT_TIMEOUT_SEC


class PoolNotConnectedError(RuntimeError):
    """Raised when an operation needs an active pool but none is open."""


class ApexBuilderPool:
    """Wraps oracledb thin-mode pool with environment tagging."""

    def __init__(self) -> None:
        self._pool: oracledb.ConnectionPool | None = None
        self._profile: Profile | None = None

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    def connect(self, profile: Profile, dsn: str, user: str, password: str) -> None:
        # Clear any existing pool first; if create_pool fails below, state stays None
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            self._profile = None
        new_pool = oracledb.create_pool(
            user=user,
            password=password,
            dsn=dsn,
            min=1,
            max=4,
            increment=1,
            getmode=oracledb.POOL_GETMODE_WAIT,
            tcp_connect_timeout=_tcp_connect_timeout_sec(),
        )
        # Only assign on success
        self._pool = new_pool
        self._profile = profile

    def disconnect(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            self._profile = None

    def get_environment(self) -> Literal["DEV", "TEST", "PROD"]:
        if self._profile is None:
            raise PoolNotConnectedError("Pool not connected")
        return self._profile.environment

    def acquire(self) -> oracledb.Connection:
        if self._pool is None:
            raise PoolNotConnectedError("Pool not connected")
        return self._pool.acquire()

    @property
    def profile(self) -> Profile | None:
        return self._profile
