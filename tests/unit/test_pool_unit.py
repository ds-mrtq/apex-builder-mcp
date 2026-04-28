# tests/unit/test_pool_unit.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.pool import (
    ApexBuilderPool,
    PoolNotConnectedError,
)
from apex_builder_mcp.schema.profile import Profile


def make_profile(env="DEV"):
    return Profile(sqlcl_name="X", environment=env, workspace="W")


def test_pool_starts_disconnected():
    p = ApexBuilderPool()
    assert not p.is_connected
    with pytest.raises(PoolNotConnectedError):
        p.get_environment()


def test_pool_connect_with_mock_oracledb(monkeypatch):
    fake_pool = MagicMock()
    fake_oracledb = MagicMock()
    fake_oracledb.create_pool = MagicMock(return_value=fake_pool)
    monkeypatch.setattr("apex_builder_mcp.connection.pool.oracledb", fake_oracledb)

    p = ApexBuilderPool()
    profile = make_profile("DEV")
    p.connect(profile=profile, dsn="host:1521/svc", user="EREPORT", password="x")

    assert p.is_connected
    assert p.get_environment() == "DEV"
    fake_oracledb.create_pool.assert_called_once()


def test_pool_disconnect(monkeypatch):
    fake_pool = MagicMock()
    fake_oracledb = MagicMock()
    fake_oracledb.create_pool = MagicMock(return_value=fake_pool)
    monkeypatch.setattr("apex_builder_mcp.connection.pool.oracledb", fake_oracledb)

    p = ApexBuilderPool()
    p.connect(profile=make_profile(), dsn="x", user="u", password="p")
    p.disconnect()
    assert not p.is_connected
    fake_pool.close.assert_called_once()


def test_pool_reconnect_failure_clears_stale_state(monkeypatch):
    """If create_pool raises during reconnect, state must be cleared (no stale pool)."""
    fake_pool_first = MagicMock()
    fake_oracledb = MagicMock()
    fake_oracledb.create_pool = MagicMock(return_value=fake_pool_first)
    monkeypatch.setattr("apex_builder_mcp.connection.pool.oracledb", fake_oracledb)

    # First connect succeeds
    p = ApexBuilderPool()
    p.connect(profile=make_profile(), dsn="x", user="u", password="p")
    assert p.is_connected

    # Second connect: create_pool raises (simulate auth failure / network down)
    fake_oracledb.create_pool = MagicMock(
        side_effect=Exception("ORA-01017: invalid username/password")
    )

    with pytest.raises(Exception, match="ORA-01017"):
        p.connect(profile=make_profile(), dsn="y", user="u", password="bad")

    # After failure: pool must be cleared (not stale)
    assert not p.is_connected
    assert p.profile is None
    # Old pool should have been closed during the cleanup
    fake_pool_first.close.assert_called_once()
