from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from apex_builder_mcp.audit.auto_export import refresh_export


def test_refresh_export_skipped_when_no_dir(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("apex_builder_mcp.audit.auto_export.run_sqlcl", fake)
    result = refresh_export(sqlcl_conn="c", app_id=100, export_dir=None)
    assert result["skipped"] is True
    fake.assert_not_called()


def test_refresh_export_runs_sqlcl(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run_sqlcl(conn, sql, **kw):
        captured["sql"] = sql
        captured["conn"] = conn
        # Touch the expected output file to simulate `apex export`
        (tmp_path / "f100.sql").write_text("-- export\n", encoding="utf-8")
        result = MagicMock()
        result.rc = 0
        result.stdout = ""
        result.cleaned = ""
        result.stderr = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.audit.auto_export.run_sqlcl", fake_run_sqlcl
    )
    result = refresh_export(sqlcl_conn="ereport_test8001", app_id=100, export_dir=tmp_path)
    assert result["skipped"] is False
    assert result["ok"] is True
    assert result["app_id"] == 100
    assert "apex export -applicationid 100" in captured["sql"]
    assert captured["conn"] == "ereport_test8001"
    assert (tmp_path / "f100.sql").exists()


def test_refresh_export_handles_db_error(monkeypatch, tmp_path: Path):
    def fake_run_sqlcl(conn, sql, **kw):
        result = MagicMock()
        result.rc = 0
        result.stdout = "ORA-12345 export failed"
        result.cleaned = "ORA-12345 export failed"
        result.stderr = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.audit.auto_export.run_sqlcl", fake_run_sqlcl
    )
    result = refresh_export(sqlcl_conn="c", app_id=100, export_dir=tmp_path)
    assert result["skipped"] is False
    assert result["ok"] is False
    assert "ORA-12345" in result["error"]


def test_refresh_export_creates_dir_if_missing(monkeypatch, tmp_path: Path):
    target = tmp_path / "subdir" / "exports"
    assert not target.exists()

    def fake_run_sqlcl(conn, sql, **kw):
        result = MagicMock()
        result.rc = 0
        result.stdout = ""
        result.cleaned = ""
        result.stderr = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.audit.auto_export.run_sqlcl", fake_run_sqlcl
    )
    refresh_export(sqlcl_conn="c", app_id=100, export_dir=target)
    assert target.exists()
