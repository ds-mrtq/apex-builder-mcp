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


@pytest.fixture
def tmp_sqlcl_profile_yaml(tmp_path):
    """Profile yaml with explicit auth_mode: sqlcl (matches the production default)."""
    p = tmp_path / "profiles_sqlcl.yaml"
    p.write_text(
        "profiles:\n"
        "  DEV1:\n"
        "    sqlcl_name: ereport_test8001\n"
        "    environment: DEV\n"
        "    workspace: EREPORT\n"
        "    auth_mode: sqlcl\n",
        encoding="utf-8",
    )
    return p


def test_connect_sqlcl_mode_skips_keyring_and_pool(monkeypatch, tmp_sqlcl_profile_yaml):
    """auth_mode=sqlcl: never touch keyring, never open oracledb pool.

    Validates the design intent — SQLcl saved-conn owns credentials in its
    own encrypted store; Python layer must not duplicate the password.
    """
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_sqlcl_profile_yaml
    )

    fake_md = MagicMock()
    fake_md.dsn = "ebstest.example:1522/TEST1"
    fake_md.user = "EREPORT"
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata",
        lambda name: fake_md,
    )

    # If get_password gets called at all, fail the test.
    def must_not_call_get_password(*args, **kwargs):
        raise AssertionError("get_password must NOT be called in sqlcl mode")

    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.get_password", must_not_call_get_password
    )

    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.ApexBuilderPool", lambda: fake_pool
    )

    verify_calls: list[str] = []

    def fake_verify(name):
        verify_calls.append(name)
        return True

    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.verify_sqlcl_connection", fake_verify
    )

    result = apex_connect(profile_name="DEV1")

    assert result["state"] == "CONNECTED:DEV"
    assert result["auth_mode"] == "sqlcl"
    assert verify_calls == ["ereport_test8001"]
    fake_pool.connect.assert_not_called()


def test_connect_sqlcl_mode_raises_when_saved_conn_unhealthy(
    monkeypatch, tmp_sqlcl_profile_yaml
):
    """If verify_sqlcl_connection fails, surface SQLCL_CONN_UNREACHABLE clearly."""
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_sqlcl_profile_yaml
    )
    fake_md = MagicMock()
    fake_md.dsn = "x"
    fake_md.user = "u"
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata", lambda n: fake_md
    )

    from apex_builder_mcp.connection.auth_mode import AuthResolutionError

    def boom(name):
        raise AuthResolutionError("sql -name ereport_test8001 returned rc=1: ORA-12541")

    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.verify_sqlcl_connection", boom
    )

    with pytest.raises(ApexBuilderError) as exc:
        apex_connect(profile_name="DEV1")

    assert exc.value.code == "SQLCL_CONN_UNREACHABLE"
    assert "ereport_test8001" in exc.value.message
    assert "ORA-12541" in exc.value.suggestion


def test_status_reports_auth_mode_after_sqlcl_connect(
    monkeypatch, tmp_sqlcl_profile_yaml
):
    """apex_status must expose auth_mode so pool_connected=false is interpretable."""
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.PROFILES_YAML", tmp_sqlcl_profile_yaml
    )
    fake_md = MagicMock()
    fake_md.dsn = "x"
    fake_md.user = "u"
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.read_connection_metadata", lambda n: fake_md
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.verify_sqlcl_connection", lambda n: True
    )

    apex_connect(profile_name="DEV1")
    s = apex_status()
    assert s["state"] == "CONNECTED:DEV"
    assert s["auth_mode"] == "sqlcl"
    assert s["pool_connected"] is False  # no oracledb pool was opened in sqlcl mode


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
