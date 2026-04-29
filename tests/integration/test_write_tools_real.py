"""Integration tests for write tools on DB DEV.

These tests verify the write tools (apex_add_page/region/item) work end-to-end
with the actual import_begin/end pattern proven in Phase 0 Gate 5.

Two fixtures:
  * `test_env_state` (TEST environment) — verifies dry-run path with no live writes
  * `dev_state` (DEV environment) — verifies the live cycle: probe write,
    metadata verify, cleanup via SQLcl heredoc

Live DEV tests use SQLcl-only auth (`auth_mode=sqlcl`) so the shared
`tools/_write_helpers.py` queries (workspace_id, metadata snapshot) execute
through `run_sqlcl` rather than oracledb pool. Cleanup mirrors the Phase 0
round_trip_proof.py pattern.
"""
from __future__ import annotations

import os

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.items import apex_add_item
from apex_builder_mcp.tools.pages import apex_add_page
from apex_builder_mcp.tools.regions import apex_add_region

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_env_state():
    """Set up TEST profile state for dry-run verification."""
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
    """Set up DEV profile state for live write verification."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Dry-run tests (TEST environment)
# ---------------------------------------------------------------------------


def test_add_page_dry_run_via_real_state(test_env_state):
    """TEST env returns dry-run preview without executing."""
    result = apex_add_page(
        app_id=100, page_id=8000, name="ITEST_PROBE",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page" in result["sql_preview"]


def test_add_region_dry_run_via_real_state(test_env_state):
    result = apex_add_region(
        app_id=100, page_id=8000, region_id=8100, name="ITEST_REGION",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_plug" in result["sql_preview"]


def test_add_item_dry_run_via_real_state(test_env_state):
    result = apex_add_item(
        app_id=100, page_id=8000, item_id=8200, region_id=8100, name="P8000_ITEM",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_item" in result["sql_preview"]


# ---------------------------------------------------------------------------
# Live DEV tests
# ---------------------------------------------------------------------------


def test_add_page_dev_live_full_cycle(dev_state):
    """Live DEV: add probe page, verify metadata, cleanup."""
    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    probe_page_id = 8500
    try:
        result = apex_add_page(
            app_id=app_id,
            page_id=probe_page_id,
            name="ITEST_PROBE",
        )
        assert result["dry_run"] is False
        assert result["after"]["pages"] == result["before"]["pages"] + 1
    finally:
        _cleanup_probe_page(app_id, probe_page_id)


def test_add_region_dev_live_full_cycle(dev_state):
    """Live DEV: add probe page + region, verify region count, cleanup."""
    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    probe_page_id = 8501
    try:
        page_result = apex_add_page(
            app_id=app_id,
            page_id=probe_page_id,
            name="ITEST_PROBE_REGION",
        )
        assert page_result["dry_run"] is False

        region_result = apex_add_region(
            app_id=app_id,
            page_id=probe_page_id,
            region_id=probe_page_id + 100,
            name="ITEST_REGION",
        )
        assert region_result["dry_run"] is False
        assert (
            region_result["after"]["regions"]
            == region_result["before"]["regions"] + 1
        )
    finally:
        _cleanup_probe_page(app_id, probe_page_id)


def test_add_item_dev_live_full_cycle(dev_state):
    """Live DEV: add probe page + region + item, verify item count, cleanup."""
    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    probe_page_id = 8502
    try:
        page_result = apex_add_page(
            app_id=app_id,
            page_id=probe_page_id,
            name="ITEST_PROBE_ITEM",
        )
        assert page_result["dry_run"] is False

        region_id = probe_page_id + 100
        region_result = apex_add_region(
            app_id=app_id,
            page_id=probe_page_id,
            region_id=region_id,
            name="ITEST_REGION_FOR_ITEM",
        )
        assert region_result["dry_run"] is False

        item_result = apex_add_item(
            app_id=app_id,
            page_id=probe_page_id,
            item_id=probe_page_id + 200,
            region_id=region_id,
            name=f"P{probe_page_id}_PROBE_ITEM",
        )
        assert item_result["dry_run"] is False
        assert (
            item_result["after"]["items"]
            == item_result["before"]["items"] + 1
        )
    finally:
        _cleanup_probe_page(app_id, probe_page_id)
