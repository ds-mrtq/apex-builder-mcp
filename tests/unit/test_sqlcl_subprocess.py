# tests/unit/test_sqlcl_subprocess.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.sqlcl_subprocess import (
    SqlclResult,
    SqlclSubprocessError,
    has_db_error,
    run_sqlcl,
    strip_banner,
)


def test_strip_banner_removes_sqlcl_intro():
    raw = """SQLcl: Release 26.1 Production on Tue Apr 28 22:43:55 2026

Copyright (c) 1982, 2026, Oracle.  All rights reserved.

Connected to:
Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production
Version 19.17.0.0.0

real result here
"""
    out = strip_banner(raw)
    assert "real result here" in out
    assert "SQLcl: Release" not in out
    assert "Copyright" not in out
    assert "Connected to:" not in out


def test_has_db_error_detects_ora():
    assert has_db_error("ORA-12345: something") is True
    assert has_db_error("ORA-06550 line 1") is True
    assert has_db_error("PLS-00306 wrong") is True
    assert has_db_error("clean output") is False


def test_run_sqlcl_invokes_subprocess(monkeypatch):
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = "result\n"
    fake_proc.stderr = ""
    fake_run = MagicMock(return_value=fake_proc)
    monkeypatch.setattr(
        "apex_builder_mcp.connection.sqlcl_subprocess.subprocess.run", fake_run
    )

    result = run_sqlcl("ereport_test8001", "select 1 from dual;")
    assert isinstance(result, SqlclResult)
    assert result.rc == 0
    assert "result" in result.stdout
    fake_run.assert_called_once()
    args = fake_run.call_args
    assert args.kwargs["input"] == "select 1 from dual;"
    assert args.kwargs["env"]["MSYS2_ARG_CONV_EXCL"] == "*"
    assert args.kwargs["timeout"] == 180


def test_run_sqlcl_failure_raises(monkeypatch):
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = "ORA-12345 boom"
    fake_proc.stderr = ""
    monkeypatch.setattr(
        "apex_builder_mcp.connection.sqlcl_subprocess.subprocess.run",
        MagicMock(return_value=fake_proc),
    )

    with pytest.raises(SqlclSubprocessError):
        run_sqlcl("conn", "x;", raise_on_db_error=True)
