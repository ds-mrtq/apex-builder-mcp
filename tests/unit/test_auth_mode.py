# tests/unit/test_auth_mode.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.auth_mode import (
    AuthMode,
    AuthResolutionError,
    resolve_auth_mode,
    verify_sqlcl_connection,
)
from apex_builder_mcp.schema.profile import Profile


def test_resolve_sqlcl_mode_returns_marker():
    profile = Profile(
        sqlcl_name="ereport_test8001",
        environment="DEV",
        workspace="EREPORT",
        auth_mode="sqlcl",
    )
    mode = resolve_auth_mode(profile)
    assert mode == AuthMode.SQLCL


def test_resolve_password_mode_returns_marker():
    profile = Profile(
        sqlcl_name="X",
        environment="DEV",
        workspace="W",
        auth_mode="password",
    )
    mode = resolve_auth_mode(profile)
    assert mode == AuthMode.PASSWORD


def test_verify_sqlcl_connection_ok(monkeypatch):
    fake_result = MagicMock()
    fake_result.rc = 0
    fake_result.stdout = "OK_CHECK\n"
    fake_result.cleaned = "OK_CHECK"

    monkeypatch.setattr(
        "apex_builder_mcp.connection.auth_mode.run_sqlcl",
        MagicMock(return_value=fake_result),
    )
    assert verify_sqlcl_connection("ereport_test8001") is True


def test_verify_sqlcl_connection_fails_on_no_check_marker(monkeypatch):
    fake_result = MagicMock()
    fake_result.rc = 0
    fake_result.stdout = "ORA-12541 listener"
    fake_result.cleaned = "ORA-12541 listener"
    monkeypatch.setattr(
        "apex_builder_mcp.connection.auth_mode.run_sqlcl",
        MagicMock(return_value=fake_result),
    )
    with pytest.raises(AuthResolutionError):
        verify_sqlcl_connection("bad_conn")
