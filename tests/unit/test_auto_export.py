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
    assert result["file_count"] >= 1
    assert result["newest_file"] == "f100.sql"
    assert "apex export -applicationid 100" in captured["sql"]
    assert captured["conn"] == "ereport_test8001"
    assert (tmp_path / "f100.sql").exists()


def test_refresh_export_detects_silent_failure(monkeypatch, tmp_path: Path):
    """Bug #5 (HT_AMMS 2026-05-20): SQLcl returns rc=0 + no DB error but
    writes nothing to disk. Must be surfaced as ok=False with FILE_NOT_PERSISTED."""
    def fake_run_sqlcl(conn, sql, **kw):
        # Simulate SQLcl exiting cleanly but not writing the file
        result = MagicMock()
        result.rc = 0
        result.stdout = "Disconnected.\n"
        result.cleaned = ""
        result.stderr = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.audit.auto_export.run_sqlcl", fake_run_sqlcl
    )
    result = refresh_export(sqlcl_conn="c", app_id=100, export_dir=tmp_path)
    assert result["skipped"] is False
    assert result["ok"] is False, "should NOT report ok=True when no file landed"
    assert result["error"] == "FILE_NOT_PERSISTED"
    assert "stdout_tail" in result
    # detail must give the user enough to debug manually
    assert "sql -name c" in result["detail"]
    assert "apex export -applicationid 100" in result["detail"]


def test_refresh_export_accepts_split_mode_writes(monkeypatch, tmp_path: Path):
    """Some apex export configurations write a split tree (no f<id>.sql)
    but multiple files in subdirs. mtime-based verify must accept this."""
    def fake_run_sqlcl(conn, sql, **kw):
        # Write into a nested split-style layout
        nested = tmp_path / "application" / "pages"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "page_00010.sql").write_text("-- page 10\n", encoding="utf-8")
        result = MagicMock()
        result.rc = 0
        result.stdout = ""
        result.cleaned = ""
        result.stderr = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.audit.auto_export.run_sqlcl", fake_run_sqlcl
    )
    result = refresh_export(sqlcl_conn="c", app_id=100, export_dir=tmp_path)
    assert result["ok"] is True
    assert result["file_count"] >= 1
    assert "page_00010.sql" in (result["newest_file"] or "")


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
        # Touch a file so the verify step passes
        target.mkdir(parents=True, exist_ok=True)
        (target / f"f100.sql").write_text("-- export\n", encoding="utf-8")
        result = MagicMock()
        result.rc = 0
        result.stdout = ""
        result.cleaned = ""
        result.stderr = ""
        return result

    monkeypatch.setattr(
        "apex_builder_mcp.audit.auto_export.run_sqlcl", fake_run_sqlcl
    )
    result = refresh_export(sqlcl_conn="c", app_id=100, export_dir=target)
    assert target.exists()
    assert result["ok"] is True
