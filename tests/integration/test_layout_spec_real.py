"""Integration test for apex_apply_layout_spec bridge."""
from __future__ import annotations

import os

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.layout_spec import apex_apply_layout_spec
from apex_builder_mcp.tools.pages import apex_add_page

pytestmark = pytest.mark.integration


@pytest.fixture
def test_env_state():
    sqlcl_name = os.environ.get("APEX_TEST_SQLCL_NAME")
    if not sqlcl_name:
        pytest.skip("APEX_TEST_SQLCL_NAME not set")
    reset_state_for_tests()
    state = get_state()
    state.set_profile(
        Profile(
            sqlcl_name=sqlcl_name,
            environment="TEST",
            workspace=os.environ.get("APEX_TEST_WORKSPACE", "EREPORT"),
            auth_mode="sqlcl",
        )
    )
    state.mark_connected()
    yield
    reset_state_for_tests()


@pytest.fixture
def dev_state():
    sqlcl_name = os.environ.get("APEX_TEST_SQLCL_NAME")
    if not sqlcl_name:
        pytest.skip("APEX_TEST_SQLCL_NAME not set")
    reset_state_for_tests()
    state = get_state()
    state.set_profile(
        Profile(
            sqlcl_name=sqlcl_name,
            environment="DEV",
            workspace=os.environ.get("APEX_TEST_WORKSPACE", "EREPORT"),
            auth_mode="sqlcl",
        )
    )
    state.mark_connected()
    yield
    reset_state_for_tests()


def _cleanup_probe_page(app_id: int, page_id: int) -> None:
    """Delete probe page via SQLcl heredoc (mirrors Phase 0 round_trip_proof)."""
    from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl

    schema = os.environ.get("APEX_TEST_SCHEMA", "EREPORT")
    workspace_id = os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")
    sql = f"""set echo off feedback off define off verify off
begin
  wwv_flow_imp.import_begin(
    p_version_yyyy_mm_dd => '2024.11.30',
    p_release => '24.2.12',
    p_default_workspace_id => {workspace_id},
    p_default_application_id => {app_id},
    p_default_id_offset => 0,
    p_default_owner => '{schema}'
  );
end;
/
begin
  begin
    wwv_flow_imp_page.remove_page(p_flow_id => {app_id}, p_page_id => {page_id});
  exception when others then null;
  end;
end;
/
begin
  wwv_flow_imp.import_end(p_auto_install_sup_obj => false);
  commit;
end;
/
exit
"""
    run_sqlcl(os.environ["APEX_TEST_SQLCL_NAME"], sql, timeout=60)


def test_layout_spec_dry_run(test_env_state):
    """TEST env: layout spec expansion returns dry-run results for each region/item."""
    spec = {
        "app_id": 100,
        "page_id": 8000,
        "regions": [
            {
                "name": "demo_region",
                "template": "t-Region",
                "grid": {"col_span": 12},
                "items": [
                    {"name": "P8000_X", "type": "TEXT"},
                    {"name": "P8000_Y", "type": "DATE"},
                ],
            },
        ],
    }
    result = apex_apply_layout_spec(spec)
    assert result["regions_added"] == 1
    assert result["items_added"] == 2
    # Each child call should also be dry_run on TEST env
    assert result["regions"][0]["dry_run"] is True
    assert result["items"][0]["dry_run"] is True


def test_layout_spec_dev_live(dev_state):
    """Live DEV: create probe page, apply layout spec to it, verify, cleanup."""
    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    probe_page_id = 8503
    try:
        page_result = apex_add_page(
            app_id=app_id,
            page_id=probe_page_id,
            name="ITEST_LAYOUT_PROBE",
        )
        assert page_result["dry_run"] is False
        before_regions = page_result["after"]["regions"]
        before_items = page_result["after"]["items"]

        spec = {
            "app_id": app_id,
            "page_id": probe_page_id,
            "regions": [
                {
                    "name": "demo_region",
                    "template": "t-Region",
                    "grid": {"col_span": 12},
                    "items": [
                        {"name": f"P{probe_page_id}_X", "type": "TEXT"},
                        {"name": f"P{probe_page_id}_Y", "type": "DATE"},
                    ],
                },
            ],
        }
        result = apex_apply_layout_spec(spec)
        assert result["regions_added"] == 1
        assert result["items_added"] == 2
        assert result["regions"][0]["dry_run"] is False
        assert result["items"][0]["dry_run"] is False

        # Verify last item snapshot reflects +1 region, +2 items vs page-only state
        last_item = result["items"][-1]
        assert last_item["after"]["regions"] >= before_regions + 1
        assert last_item["after"]["items"] >= before_items + 2
    finally:
        _cleanup_probe_page(app_id, probe_page_id)
