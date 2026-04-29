from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.apex_api.sql_guard import SqlGuardError
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.inspect_db import (
    apex_dependencies,
    apex_describe_table,
    apex_get_source,
    apex_list_tables,
    apex_run_sql,
    apex_search_objects,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


def _setup_state(env: str = "DEV") -> None:
    profile = Profile(
        sqlcl_name="ereport_test8001",
        environment=env,  # type: ignore[arg-type]
        workspace="EREPORT",
    )
    state = get_state()
    state.set_profile(profile)
    state.mark_connected()


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


# ---------------------------------------------------------------------------
# apex_search_objects (Plan 2B-6)
# ---------------------------------------------------------------------------


def test_search_objects_rejects_invalid_pattern(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_search_objects(pattern="bad; drop")
    assert exc_info.value.code == "INVALID_PATTERN"


def test_search_objects_rejects_empty_pattern(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_search_objects(pattern="")
    assert exc_info.value.code == "INVALID_PATTERN"


def test_search_objects_rejects_invalid_type(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_search_objects(pattern="EMP%", object_types=["WIDGET"])
    assert exc_info.value.code == "INVALID_OBJECT_TYPE"


def test_search_objects_runs_query(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_search_objects",
        lambda profile, pattern, object_types, max_rows: [
            {
                "owner": "EREPORT",
                "object_name": "EMP_PKG",
                "object_type": "PACKAGE",
                "status": "VALID",
                "last_ddl_time": None,
            },
            {
                "owner": "EREPORT",
                "object_name": "EMP_VW",
                "object_type": "VIEW",
                "status": "VALID",
                "last_ddl_time": None,
            },
        ],
    )
    result = apex_search_objects(pattern="EMP%")
    assert result["count"] == 2
    assert result["objects"][0]["object_name"] == "EMP_PKG"
    assert result["pattern"] == "EMP%"


def test_search_objects_with_type_filter(monkeypatch):
    _setup_state()
    captured: dict = {}

    def fake_query(profile, pattern, object_types, max_rows):
        captured["object_types"] = object_types
        return [
            {
                "owner": "EREPORT",
                "object_name": "EMP_PKG",
                "object_type": "PACKAGE",
                "status": "VALID",
                "last_ddl_time": None,
            }
        ]

    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_search_objects", fake_query
    )
    result = apex_search_objects(pattern="EMP%", object_types=["PACKAGE", "VIEW"])
    assert result["count"] == 1
    assert result["object_types"] == ["PACKAGE", "VIEW"]
    # Verify the helper received the type filter
    assert captured["object_types"] == ["PACKAGE", "VIEW"]


def test_search_objects_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_search_objects(pattern="EMP%")
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_dependencies (Plan 2B-6)
# ---------------------------------------------------------------------------


def test_dependencies_rejects_invalid_object_name(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(SqlGuardError):
        apex_dependencies(object_name="bad; drop")


def test_dependencies_rejects_invalid_type(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db._get_pool", lambda: fake_pool
    )
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_dependencies(object_name="EMP_PKG", object_type="WIDGET")
    assert exc_info.value.code == "INVALID_OBJECT_TYPE"


def test_dependencies_runs_two_queries(monkeypatch):
    _setup_state()
    uses_row = {
        "owner": "EREPORT",
        "name": "EMP_PKG",
        "type": "PACKAGE BODY",
        "referenced_owner": "EREPORT",
        "referenced_name": "EMP",
        "referenced_type": "TABLE",
    }
    used_by_row = {
        "owner": "EREPORT",
        "name": "OTHER_PKG",
        "type": "PACKAGE BODY",
        "referenced_owner": "EREPORT",
        "referenced_name": "EMP_PKG",
        "referenced_type": "PACKAGE",
    }
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_dependencies",
        lambda profile, object_name, object_type, max_rows: (
            [uses_row],
            [used_by_row],
        ),
    )
    result = apex_dependencies(object_name="EMP_PKG")
    assert result["uses_count"] == 1
    assert result["used_by_count"] == 1
    assert result["uses"][0]["referenced_name"] == "EMP"
    assert result["used_by"][0]["name"] == "OTHER_PKG"
    assert result["object_name"] == "EMP_PKG"


def test_dependencies_with_type_filter(monkeypatch):
    _setup_state()
    captured: dict = {}

    def fake_query(profile, object_name, object_type, max_rows):
        captured["object_type"] = object_type
        return [], []

    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_dependencies", fake_query
    )
    result = apex_dependencies(object_name="EMP_PKG", object_type="PACKAGE")
    assert result["object_type"] == "PACKAGE"
    assert result["uses_count"] == 0
    assert result["used_by_count"] == 0
    assert captured["object_type"] == "PACKAGE"


def test_dependencies_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_dependencies(object_name="EMP_PKG")
    assert exc_info.value.code == "NOT_CONNECTED"
