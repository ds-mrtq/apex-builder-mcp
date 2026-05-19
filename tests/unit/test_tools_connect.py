# tests/unit/test_tools_connect.py
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.state import reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
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


def test_connect_raises_cred_missing_when_keyring_empty(monkeypatch, tmp_profiles_yaml):
    """No password in keyring => CRED_MISSING, NEVER an interactive prompt.

    Regression: previously apex_connect called getpass.getpass(prompt_if_missing=True)
    which blocks forever when stdin is an MCP JSON-RPC pipe (no TTY).
    """
    monkeypatch.setattr("apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_profiles_yaml)

    fake_md = MagicMock()
    fake_md.dsn = "x"
    fake_md.user = "u"
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata", lambda n: fake_md
    )

    captured: dict[str, object] = {}

    def fake_get_password(name, prompt_if_missing=False, save_after_prompt=False):
        captured["prompt_if_missing"] = prompt_if_missing
        return None  # keyring empty

    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.get_password", fake_get_password
    )

    with pytest.raises(ApexBuilderError) as exc:
        apex_connect(profile_name="DEV1")

    assert exc.value.code == "CRED_MISSING"
    assert captured["prompt_if_missing"] is False, (
        "apex_connect MUST NOT request an interactive password prompt"
    )


def test_connect_timeout_names_active_stage(monkeypatch, tmp_profiles_yaml):
    """If apex_connect overruns its budget, the error must surface which stage hung."""
    monkeypatch.setattr("apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_profiles_yaml)
    monkeypatch.setenv("APEX_BUILDER_CONNECT_TIMEOUT_SEC", "5")  # min allowed

    # Simulate connmgr lookup that hangs longer than the budget.
    def slow_md(name):
        time.sleep(20)
        return MagicMock()

    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata", slow_md
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.get_password",
        lambda *a, **kw: "p",
    )

    started = time.monotonic()
    with pytest.raises(ApexBuilderError) as exc:
        apex_connect(profile_name="DEV1")
    elapsed = time.monotonic() - started

    assert exc.value.code == "CONNECT_TIMEOUT"
    assert exc.value.metadata["stage"] == "read_connection_metadata"
    assert exc.value.metadata["timeout_sec"] == 5
    assert elapsed < 10, f"timeout should fire ~5s, got {elapsed:.1f}s"


def test_connect_auto_loads_read_categories(monkeypatch, tmp_profiles_yaml):
    """After successful connect, READ_DB + READ_APEX categories should be loaded."""
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_profiles_yaml
    )
    fake_md = MagicMock()
    fake_md.dsn = "x"
    fake_md.user = "u"
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata", lambda n: fake_md
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.get_password", lambda *a, **kw: "p"
    )
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.ApexBuilderPool", lambda: fake_pool
    )

    from apex_builder_mcp.registry.categories import Category
    from apex_builder_mcp.tools.lazy import _get_loader, _reset_loader_for_tests
    _reset_loader_for_tests()

    apex_connect(profile_name="DEV1")

    loader = _get_loader()
    loaded = loader.loaded_categories()
    assert Category.READ_DB in loaded
    assert Category.READ_APEX in loaded
