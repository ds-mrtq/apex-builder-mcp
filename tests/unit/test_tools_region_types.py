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
