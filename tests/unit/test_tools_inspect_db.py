from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.apex_api.sql_guard import SqlGuardError
from apex_builder_mcp.tools.inspect_db import (
    apex_describe_table,
    apex_get_source,
    apex_list_tables,
    apex_run_sql,
)


def test_run_sql_rejects_ddl(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(SqlGuardError):
        apex_run_sql("drop table emp")


def test_run_sql_runs_select(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.description = [("X", None, None, None, None, None, None)]
    fake_cur.fetchmany.return_value = [(1,), (2,)]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    result = apex_run_sql("select 1 as x from dual")
    assert result["columns"] == ["X"]
    assert len(result["rows"]) == 2


def test_list_tables_validates_schema_name(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(SqlGuardError):
        apex_list_tables(schema="bad; drop")


def test_describe_table_validates_table_name(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(SqlGuardError):
        apex_describe_table(table_name="x@remote")


def test_get_source_validates(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(SqlGuardError):
        apex_get_source(object_name="bad; drop", object_type="PACKAGE")


def test_get_source_rejects_invalid_object_type(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(ValueError):
        apex_get_source(object_name="MY_PKG", object_type="WIDGET")


def test_list_tables_runs_query(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [("EMP", 14, None), ("DEPT", 4, None)]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    result = apex_list_tables()
    assert result["count"] == 2
    assert result["tables"][0]["table_name"] == "EMP"
