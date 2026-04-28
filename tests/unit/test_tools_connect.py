# tests/unit/test_tools_connect.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.state import reset_state_for_tests
from apex_builder_mcp.tools.connection import apex_connect, apex_disconnect, apex_status


@pytest.fixture(autouse=True)
def reset_state():
    reset_state_for_tests()
    from apex_builder_mcp.tools.connection import _reset_pool_for_tests
    _reset_pool_for_tests()
    yield
    reset_state_for_tests()
    _reset_pool_for_tests()


def test_status_unconfigured():
    s = apex_status()
    assert s["state"] == "UNCONFIGURED"


def test_connect_sets_state(monkeypatch, tmp_profiles_yaml):
    monkeypatch.setattr("apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_profiles_yaml)

    fake_md = MagicMock()
    fake_md.dsn = "10.0.0.10:1521/ORCLPDB"
    fake_md.user = "EREPORT"
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata",
        lambda name: fake_md,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.get_password",
        lambda name, prompt_if_missing=True, save_after_prompt=True: "secret",
    )

    fake_pool = MagicMock()
    monkeypatch.setattr("apex_builder_mcp.tools.connection.ApexBuilderPool", lambda: fake_pool)

    result = apex_connect(profile_name="DEV1")
    assert result["state"] == "CONNECTED:DEV"
    fake_pool.connect.assert_called_once()


def test_disconnect_after_connect(monkeypatch, tmp_profiles_yaml):
    monkeypatch.setattr("apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_profiles_yaml)
    fake_md = MagicMock()
    fake_md.dsn = "x"
    fake_md.user = "u"
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata",
        lambda n: fake_md,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.get_password",
        lambda *a, **kw: "p",
    )
    fake_pool = MagicMock()
    monkeypatch.setattr("apex_builder_mcp.tools.connection.ApexBuilderPool", lambda: fake_pool)

    apex_connect(profile_name="DEV1")
    result = apex_disconnect()
    assert result["state"] == "DISCONNECTED"
