from __future__ import annotations

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


# ---------------------------------------------------------------------------
# apex_run_sql (now branches via query_run_sql helper)
# ---------------------------------------------------------------------------


def test_run_sql_rejects_ddl():
    with pytest.raises(SqlGuardError):
        apex_run_sql("drop table emp")


def test_run_sql_runs_select_via_helper(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_run_sql",
        lambda profile, sql, max_rows: {
            "columns": ["X"],
            "rows": [[1], [2]],
            "row_count": 2,
        },
    )
    result = apex_run_sql("select 1 as x from dual")
    assert result["columns"] == ["X"]
    assert len(result["rows"]) == 2


def test_run_sql_caps_max_rows(monkeypatch):
    _setup_state()
    captured: dict = {}

    def fake_query(profile, sql, max_rows):
        captured["max_rows"] = max_rows
        return {"columns": ["X"], "rows": [], "row_count": 0}

    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_run_sql", fake_query
    )
    apex_run_sql("select 1 as x from dual", max_rows=999_999)
    # MAX_ROWS in inspect_db is 10_000 — caller cap should be applied
    assert captured["max_rows"] == 10_000


def test_run_sql_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_run_sql("select 1 from dual")
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_list_tables
# ---------------------------------------------------------------------------


def test_list_tables_validates_schema_name():
    with pytest.raises(SqlGuardError):
        apex_list_tables(schema="bad; drop")


def test_list_tables_runs_query(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_list_tables",
        lambda profile, schema: [
            {"table_name": "EMP", "num_rows": 14, "last_analyzed": None},
            {"table_name": "DEPT", "num_rows": 4, "last_analyzed": None},
        ],
    )
    result = apex_list_tables()
    assert result["count"] == 2
    assert result["tables"][0]["table_name"] == "EMP"


def test_list_tables_with_schema(monkeypatch):
    _setup_state()
    captured: dict = {}

    def fake_query(profile, schema):
        captured["schema"] = schema
        return [{"table_name": "EMP", "num_rows": 14, "last_analyzed": None}]

    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_list_tables", fake_query
    )
    result = apex_list_tables(schema="EREPORT")
    assert result["count"] == 1
    assert captured["schema"] == "EREPORT"


def test_list_tables_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_tables()
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_describe_table
# ---------------------------------------------------------------------------


def test_describe_table_validates_table_name():
    with pytest.raises(SqlGuardError):
        apex_describe_table(table_name="x@remote")


def test_describe_table_runs_query(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_describe_table",
        lambda profile, table_name, schema: [
            {"name": "ID", "type": "NUMBER", "length": 22,
             "nullable": False, "default": None},
            {"name": "NAME", "type": "VARCHAR2", "length": 100,
             "nullable": True, "default": None},
        ],
    )
    result = apex_describe_table(table_name="EMP")
    assert result["table_name"] == "EMP"
    assert len(result["columns"]) == 2
    assert result["columns"][0]["name"] == "ID"


def test_describe_table_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_describe_table(table_name="EMP")
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_get_source
# ---------------------------------------------------------------------------


def test_get_source_validates():
    with pytest.raises(SqlGuardError):
        apex_get_source(object_name="bad; drop", object_type="PACKAGE")


def test_get_source_rejects_invalid_object_type():
    with pytest.raises(ValueError):
        apex_get_source(object_name="MY_PKG", object_type="WIDGET")


def test_get_source_runs_query(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_db.query_get_source",
        lambda profile, object_name, object_type, schema: [
            "package my_pkg as\n",
            "  procedure foo;\n",
            "end my_pkg;\n",
        ],
    )
    result = apex_get_source(object_name="MY_PKG", object_type="PACKAGE")
    assert result["object_name"] == "MY_PKG"
    assert result["object_type"] == "PACKAGE"
    assert "package my_pkg" in result["source"]
    assert result["line_count"] == 3


def test_get_source_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_get_source(object_name="MY_PKG", object_type="PACKAGE")
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_search_objects (Plan 2B-6)
# ---------------------------------------------------------------------------


def test_search_objects_rejects_invalid_pattern():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_search_objects(pattern="bad; drop")
    assert exc_info.value.code == "INVALID_PATTERN"


def test_search_objects_rejects_empty_pattern():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_search_objects(pattern="")
    assert exc_info.value.code == "INVALID_PATTERN"


def test_search_objects_rejects_invalid_type():
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


def test_dependencies_rejects_invalid_object_name():
    with pytest.raises(SqlGuardError):
        apex_dependencies(object_name="bad; drop")


def test_dependencies_rejects_invalid_type():
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
