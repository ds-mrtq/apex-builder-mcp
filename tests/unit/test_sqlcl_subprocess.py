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


def test_run_sqlcl_sets_nls_lang_utf8_by_default(monkeypatch):
    """Bug #3 (HT_AMMS 2026-05-20): Without NLS_LANG=AL32UTF8 in subprocess
    env, SQLcl on Windows defaults to WE8MSWIN1252 and double-encodes
    UTF-8 strings passed via stdin (e.g. "Cấu hình" -> "Cáº¥u hÃ¬nh")."""
    fake_proc = MagicMock(returncode=0, stdout="", stderr="")
    captured = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return fake_proc

    monkeypatch.delenv("APEX_BUILDER_NLS_LANG", raising=False)
    monkeypatch.setattr(
        "apex_builder_mcp.connection.sqlcl_subprocess.subprocess.run", fake_run
    )
    run_sqlcl("conn", "select 1 from dual;")
    assert captured["env"]["NLS_LANG"] == "AMERICAN_AMERICA.AL32UTF8"


def test_run_sqlcl_honors_apex_builder_nls_lang_override(monkeypatch):
    """Operator can override NLS_LANG via env var if their DB charset isn't UTF-8."""
    fake_proc = MagicMock(returncode=0, stdout="", stderr="")
    captured = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return fake_proc

    monkeypatch.setenv("APEX_BUILDER_NLS_LANG", "VIETNAMESE_VIETNAM.UTF8")
    monkeypatch.setattr(
        "apex_builder_mcp.connection.sqlcl_subprocess.subprocess.run", fake_run
    )
    run_sqlcl("conn", "select 1 from dual;")
    assert captured["env"]["NLS_LANG"] == "VIETNAMESE_VIETNAM.UTF8"


def test_classify_sqlcl_failure_recognizes_ora_12514():
    """Bug #10 (HT_AMMS 2026-05-20): the canonical 'service not registered'
    error must be classified as DB-unreachable with an actionable hint."""
    from apex_builder_mcp.connection.sqlcl_subprocess import (
        SqlclResult,
        classify_sqlcl_failure,
    )
    result = SqlclResult(
        rc=1,
        stdout=(
            "Connection failed\n"
            "  USER          = ereport\n"
            "  URL           = ereport_test8001\n"
            "  Error Message = ORA-12514: Cannot connect to database. "
            "Service TEST1 is not registered with the listener at host ebstest.example.vn port 1522.\n"
        ),
        stderr="",
    )
    c = classify_sqlcl_failure(result)
    assert c is not None
    assert c["ora_code"] == "ORA-12514"
    assert "TEST1" in c["ora_line"]
    assert "listener" in c["hint"].lower() or "instance" in c["hint"].lower()


def test_classify_sqlcl_failure_recognizes_ora_01017():
    """Credentials rotated — distinguishable from network issues."""
    from apex_builder_mcp.connection.sqlcl_subprocess import (
        SqlclResult,
        classify_sqlcl_failure,
    )
    result = SqlclResult(
        rc=1,
        stdout="ORA-01017: invalid username/password; logon denied\n",
        stderr="",
    )
    c = classify_sqlcl_failure(result)
    assert c is not None
    assert c["ora_code"] == "ORA-01017"
    assert "credential" in c["hint"].lower() or "password" in c["hint"].lower()


def test_classify_sqlcl_failure_recognizes_connection_refused():
    """Plain-text 'Connection refused' (e.g. socket-layer rejection)
    classified even without ORA code."""
    from apex_builder_mcp.connection.sqlcl_subprocess import (
        SqlclResult,
        classify_sqlcl_failure,
    )
    result = SqlclResult(
        rc=1,
        stdout="",
        stderr="Connection refused: connect at 172.16.0.90:1521\n",
    )
    c = classify_sqlcl_failure(result)
    assert c is not None
    assert c["ora_code"] == ""
    assert "refused" in c["ora_line"].lower()


def test_sqlcl_or_raise_surfaces_db_unreachable(monkeypatch):
    """End-to-end: tool helper -> run_sqlcl -> classification -> DB_UNREACHABLE.

    Reproduces the HT_AMMS Session 2 scenario: a read tool calls SQLcl,
    SQLcl returns rc=1 with ORA-12514 in stdout. Before the fix the tool
    raised SQLCL_QUERY_FAIL rc=1 (non-actionable). After: raises
    DB_UNREACHABLE with the ORA line + hint + stdout_tail in metadata.
    """
    from apex_builder_mcp.tools._read_helpers import _sqlcl_or_raise
    from apex_builder_mcp.schema.profile import Profile
    from apex_builder_mcp.schema.errors import ApexBuilderError

    profile = Profile(
        sqlcl_name="ereport_test8001",
        environment="DEV",
        workspace="EREPORT",
        auth_mode="sqlcl",
    )
    fake_proc = MagicMock(
        returncode=1,
        stdout=(
            "Connection failed\n"
            "  Error Message = ORA-12514: Cannot connect to database. "
            "Service TEST1 is not registered.\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(
        "apex_builder_mcp.connection.sqlcl_subprocess.subprocess.run",
        MagicMock(return_value=fake_proc),
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        _sqlcl_or_raise(profile, "select 1 from dual", tool_label="probe")

    err = exc_info.value
    assert err.code == "DB_UNREACHABLE", (
        f"expected DB_UNREACHABLE, got {err.code} — Bug #10 regression"
    )
    assert "ORA-12514" in err.message
    assert "probe" in err.message  # the tool label is preserved
    assert err.metadata["ora_code"] == "ORA-12514"
    assert err.metadata["sqlcl_rc"] == 1
    assert "ORA-12514" in err.metadata["stdout_tail"]
    # Suggestion must include the saved-connection name so anh can probe
    assert "ereport_test8001" in err.suggestion


def test_sqlcl_or_raise_falls_back_with_evidence_on_unknown_failure(monkeypatch):
    """Unrecognised SQLcl failures still surface stdout/stderr tails."""
    from apex_builder_mcp.tools._read_helpers import _sqlcl_or_raise
    from apex_builder_mcp.schema.profile import Profile
    from apex_builder_mcp.schema.errors import ApexBuilderError

    profile = Profile(
        sqlcl_name="conn", environment="DEV", workspace="W", auth_mode="sqlcl"
    )
    fake_proc = MagicMock(
        returncode=1,
        stdout="ORA-00942: table or view does not exist\nat line 1\n",
        stderr="extra stderr context\n",
    )
    monkeypatch.setattr(
        "apex_builder_mcp.connection.sqlcl_subprocess.subprocess.run",
        MagicMock(return_value=fake_proc),
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        _sqlcl_or_raise(profile, "select 1 from dual", tool_label="probe")

    err = exc_info.value
    # ORA-00942 is a real query error, not a connection error -> generic code
    assert err.code == "SQLCL_QUERY_FAIL"
    # Evidence (stdout/stderr tails) must be surfaced — was dropped before
    assert "ORA-00942" in err.suggestion
    assert "extra stderr context" in err.suggestion
    assert err.metadata["stdout_tail"]
    assert err.metadata["stderr_tail"]


def test_classify_sqlcl_failure_returns_none_for_unknown_failure():
    """Unrecognised rc!=0 returns None so caller falls back to generic error."""
    from apex_builder_mcp.connection.sqlcl_subprocess import (
        SqlclResult,
        classify_sqlcl_failure,
    )
    result = SqlclResult(
        rc=1,
        stdout="ORA-00942: table or view does not exist\n",  # query-level, not connection
        stderr="",
    )
    assert classify_sqlcl_failure(result) is None


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
