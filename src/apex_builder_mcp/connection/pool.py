# src/apex_builder_mcp/connection/pool.py
from __future__ import annotations

from typing import Literal

import oracledb

from apex_builder_mcp.schema.profile import Profile


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
        if self._pool is not None:
            self._pool.close()
        self._pool = oracledb.create_pool(
            user=user,
            password=password,
            dsn=dsn,
            min=1,
            max=4,
            increment=1,
            getmode=oracledb.POOL_GETMODE_WAIT,
        )
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
