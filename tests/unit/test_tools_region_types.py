"""Unit tests for tools/region_types.py (Plan 2B-3).

Coverage:
  * apex_add_form_region          - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
  * apex_add_interactive_grid     - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
  * apex_add_interactive_report   - 1 test  (TOOL_DEFERRED)
  * apex_add_master_detail        - 1 test  (TOOL_DEFERRED)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.region_types import (
    apex_add_form_region,
    apex_add_interactive_grid,
    apex_add_interactive_report,
    apex_add_master_detail,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


def _setup_state(env="DEV"):
    profile = Profile(
        sqlcl_name="ereport_test8001",
        environment=env,
        workspace="EREPORT",
    )
    state = get_state()
    state.set_profile(profile)
    state.mark_connected()


# ---------------------------------------------------------------------------
# apex_add_form_region
# ---------------------------------------------------------------------------


def test_add_form_region_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_form_region(
            app_id=100, page_id=8700, region_id=8701,
            table_name="EMP", name="EMP_FORM",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_form_region_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_form_region(
            app_id=100, page_id=8700, region_id=8701,
            table_name="EMP", name="EMP_FORM",
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_form_region_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_form_region(
        app_id=100, page_id=8700, region_id=8701,
        table_name="EMP", name="EMP_FORM",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_plug" in result["sql_preview"]
    assert "NATIVE_FORM" in result["sql_preview"]
    assert "p_query_table => 'EMP'" in result["sql_preview"]
    assert result["region_id"] == 8701


def test_add_form_region_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=67, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.refresh_export",
        lambda **kw: {"skipped": True},
    )
    result = apex_add_form_region(
        app_id=100, page_id=8700, region_id=8701,
        table_name="EMP", name="EMP_FORM",
    )
    assert result["dry_run"] is False
    assert result["region_id"] == 8701
    assert result["table_name"] == "EMP"
    assert result["after"]["regions"] == 67
    fake_sess.execute.assert_called_once()


# ---------------------------------------------------------------------------
# apex_add_interactive_grid
# ---------------------------------------------------------------------------


def test_add_ig_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_interactive_grid(
            app_id=100, page_id=8700, region_id=8702,
            sql_query="select * from emp", name="EMP_IG",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_ig_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_interactive_grid(
            app_id=100, page_id=8700, region_id=8702,
            sql_query="select * from emp", name="EMP_IG",
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_ig_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_interactive_grid(
        app_id=100, page_id=8700, region_id=8702,
        sql_query="select * from emp", name="EMP_IG",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_plug" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_interactive_grid" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_ig_report" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_ig_report_view" in result["sql_preview"]
    assert "NATIVE_IG" in result["sql_preview"]
    assert result["region_id"] == 8702
    # Derived ids
    assert result["ig_id"] == 8702
    assert result["report_id"] == 8703
    assert result["view_id"] == 8704


def test_add_ig_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=67, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.refresh_export",
        lambda **kw: {"skipped": True},
    )
    result = apex_add_interactive_grid(
        app_id=100, page_id=8700, region_id=8702,
        sql_query="select * from emp", name="EMP_IG",
    )
    assert result["dry_run"] is False
    assert result["region_id"] == 8702
    assert result["after"]["regions"] == 67
    fake_sess.execute.assert_called_once()


def test_add_ig_rejects_trailing_order_by():
    """Bug #1 (HT_AMMS 2026-05-20): APEX IG rejects ORDER BY in source SQL.

    Without this guard, the tool reports success while the region is created
    in a broken state (ORA-01403 at runtime + RED region in Page Designer).
    """
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_interactive_grid(
            app_id=100, page_id=8700, region_id=8702,
            sql_query="select col_a, col_b from t1 order by col_a, col_b",
            name="IG_WITH_ORDER",
        )
    assert exc_info.value.code == "IG_SQL_HAS_ORDER_BY"
    assert "ORDER BY" in exc_info.value.message
    # The offending SQL must be preserved as evidence
    assert "order by" in (exc_info.value.sql_attempted or "").lower()


def test_add_ig_rejects_order_by_with_whitespace_and_semicolon():
    """ORDER BY tail detector handles trailing semicolon + multi-line."""
    _setup_state(env="DEV")
    sql = """select col_a, col_b
             from t1
             where col_a > 0
             ORDER BY col_a desc
             ;"""
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_interactive_grid(
            app_id=100, page_id=8700, region_id=8702,
            sql_query=sql, name="IG",
        )
    assert exc_info.value.code == "IG_SQL_HAS_ORDER_BY"


def test_add_ig_accepts_sql_without_order_by():
    """SQL without ORDER BY proceeds normally (dry-run on TEST)."""
    _setup_state(env="TEST")
    result = apex_add_interactive_grid(
        app_id=100, page_id=8700, region_id=8702,
        sql_query="select col_a, col_b from t1 where col_a > 0",
        name="IG_NO_ORDER",
    )
    assert result["dry_run"] is True


def test_add_ig_with_columns_emits_full_metadata_graph():
    """Bug #2c fix: with columns supplied, PL/SQL body must include
    create_region_column AND create_ig_report_column for each column,
    linking the per-view column to the region column by ID."""
    _setup_state(env="TEST")
    cols = [
        {"name": "lane_code", "data_type": "VARCHAR2"},
        {"name": "step_code", "data_type": "VARCHAR2"},
        {"name": "display_order", "data_type": "NUMBER"},
    ]
    result = apex_add_interactive_grid(
        app_id=100, page_id=8700, region_id=200,
        sql_query="select lane_code, step_code, display_order from t1",
        name="IG_STEP_CFG",
        columns=cols,
    )
    body = result["sql_preview"]
    assert result["column_count"] == 3
    assert result["warnings"] == []  # no warning when columns supplied

    # Per-column region column blocks
    assert body.count("create_region_column") == 3
    assert "p_name => 'lane_code'" in body
    assert "p_name => 'step_code'" in body
    assert "p_name => 'display_order'" in body
    assert "p_data_type => 'VARCHAR2'" in body
    assert "p_data_type => 'NUMBER'" in body

    # Per-view column blocks
    assert body.count("create_ig_report_column") == 3
    # Must reference the region_col_id we just created (FK linkage)
    # ID layout: region_col base = region_id * 1000 = 200000, 200001, 200002
    # ig_report_col base = region_id * 1000 + 500 = 200500, 200501, 200502
    assert "p_id => 200000" in body  # first region_column
    assert "p_id => 200500" in body  # first ig_report_column
    assert "p_column_id => 200000" in body  # FK from first ig_report_column
    assert "p_column_id => 200001" in body  # FK from second
    assert "p_column_id => 200002" in body  # FK from third


def test_add_ig_without_columns_emits_warning():
    """Legacy path: columns=None still creates the bare IG but flags the
    Bug #2c risk in the response so caller knows Save will fail."""
    _setup_state(env="TEST")
    result = apex_add_interactive_grid(
        app_id=100, page_id=8700, region_id=200,
        sql_query="select * from t1",
        name="IG",
    )
    assert result["column_count"] == 0
    assert len(result["warnings"]) == 1
    assert "ORA-01400" in result["warnings"][0]
    # Body must NOT contain column blocks
    assert "create_region_column" not in result["sql_preview"]
    assert "create_ig_report_column" not in result["sql_preview"]


def test_add_ig_rejects_empty_columns_list():
    """columns=[] is ambiguous (skip seeding vs. typo) — reject explicitly."""
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc:
        apex_add_interactive_grid(
            app_id=100, page_id=8700, region_id=200,
            sql_query="select x from t1", name="IG",
            columns=[],
        )
    assert exc.value.code == "IG_COLUMNS_EMPTY"


def test_add_ig_rejects_column_with_missing_name():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc:
        apex_add_interactive_grid(
            app_id=100, page_id=8700, region_id=200,
            sql_query="select x from t1", name="IG",
            columns=[{"data_type": "VARCHAR2"}],
        )
    assert exc.value.code == "IG_COLUMNS_BAD_NAME"


def test_add_ig_rejects_unsupported_data_type():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc:
        apex_add_interactive_grid(
            app_id=100, page_id=8700, region_id=200,
            sql_query="select x from t1", name="IG",
            columns=[{"name": "x", "data_type": "BFILE"}],
        )
    assert exc.value.code == "IG_COLUMNS_BAD_TYPE"


def test_add_ig_data_type_uppercased():
    """Accept lowercase data_type for caller convenience (uppercase internally)."""
    _setup_state(env="TEST")
    result = apex_add_interactive_grid(
        app_id=100, page_id=8700, region_id=200,
        sql_query="select x from t1", name="IG",
        columns=[{"name": "x", "data_type": "varchar2"}],
    )
    assert "p_data_type => 'VARCHAR2'" in result["sql_preview"]


def test_add_ig_does_not_misfire_on_inline_order_by_string():
    """A column named 'order_by_col' or string literal containing 'order by'
    shouldn't trigger the guard — the regex targets only trailing clauses."""
    _setup_state(env="TEST")
    # ORDER BY mentioned in WHERE clause as identifier — not a clause
    sql = "select col_a, order_by_col from t1 where col_a is not null"
    result = apex_add_interactive_grid(
        app_id=100, page_id=8700, region_id=8702,
        sql_query=sql, name="IG",
    )
    assert result["dry_run"] is True


# ---------------------------------------------------------------------------
# Deferred tools
# ---------------------------------------------------------------------------


def test_add_interactive_report_deferred():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_interactive_report(
            app_id=100, page_id=8700, region_id=8702,
            sql_query="select * from emp", name="EMP_IR",
        )
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_add_master_detail_deferred():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_master_detail(
            app_id=100, page_id=8700,
            master_region_id=8710, detail_region_id=8720,
            master_table="DEPT", detail_table="EMP",
            link_column="DEPTNO", name="DEPT_EMP_MD",
        )
    assert exc_info.value.code == "TOOL_DEFERRED"
