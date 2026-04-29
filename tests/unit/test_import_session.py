from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.apex_api.import_session import (
    ImportSession,
    ImportSessionError,
)


def test_import_session_renders_full_block(monkeypatch):
    captured: list[str] = []

    def fake_run_sqlcl(conn, sql, **kw):
        captured.append(sql)
        result = MagicMock()
        result.rc = 0
        result.stdout = ""
        result.stderr = ""
        result.cleaned = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.apex_api.import_session.run_sqlcl", fake_run_sqlcl
    )

    sess = ImportSession(
        sqlcl_conn="ereport_test8001",
        workspace_id=100002,
        application_id=100,
        schema="EREPORT",
    )
    body = "  wwv_flow_imp_page.create_page(p_id => 8000, p_name => 'TEST');"
    sess.execute(body)

    assert len(captured) == 1
    sql_sent = captured[0]
    assert "wwv_flow_imp.import_begin" in sql_sent
    assert "p_default_workspace_id => 100002" in sql_sent
    assert "p_default_application_id => 100" in sql_sent
    assert "p_default_owner => 'EREPORT'" in sql_sent
    assert "wwv_flow_imp_page.create_page" in sql_sent
    assert "wwv_flow_imp.import_end" in sql_sent


def test_import_session_raises_on_db_error(monkeypatch):
    def fake_run_sqlcl(conn, sql, **kw):
        result = MagicMock()
        result.rc = 0
        result.stdout = "ORA-20001 boom"
        result.cleaned = "ORA-20001 boom"
        result.stderr = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.apex_api.import_session.run_sqlcl", fake_run_sqlcl
    )
    sess = ImportSession("c", 1, 100, "S")
    with pytest.raises(ImportSessionError):
        sess.execute("  null;")


def test_import_session_raises_on_nonzero_rc(monkeypatch):
    def fake_run_sqlcl(conn, sql, **kw):
        result = MagicMock()
        result.rc = 1
        result.stdout = ""
        result.cleaned = ""
        result.stderr = "boom"
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.apex_api.import_session.run_sqlcl", fake_run_sqlcl
    )
    sess = ImportSession("c", 1, 100, "S")
    with pytest.raises(ImportSessionError):
        sess.execute("  null;")
