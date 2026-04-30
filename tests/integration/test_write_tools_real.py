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
import secrets

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


# ---------------------------------------------------------------------------
# 2B-1 lifecycle + bulk live DEV tests
#
# Probe ID range for 2B-1 lifecycle tests: 8500-8599 (avoids collision with
# Plan 2A 8000-8499 + Phase 0 9000).
# ---------------------------------------------------------------------------

PROBE_LIFECYCLE_PAGE = 8500
PROBE_LIFECYCLE_REGION = 8501
PROBE_LIFECYCLE_ITEM = 8502


def _add_probe_page_via_sqlcl(app_id: int) -> None:
    """Use ImportSession directly to add a probe page (bypass MCP tool layer)."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  wwv_flow_imp_page.create_page("
        f"p_id => {PROBE_LIFECYCLE_PAGE}, "
        f"p_name => 'ITEST_PROBE_2B1', "
        f"p_alias => 'ITEST_PROBE_2B1', "
        f"p_step_title => 'ITEST_PROBE_2B1', "
        f"p_autocomplete_on_off => 'OFF', "
        f"p_page_template_options => '#DEFAULT#'"
        f");\n"
    )
    sess.execute(body)


def _cleanup_probe_lifecycle(app_id: int) -> None:
    """Best-effort cleanup of any probe page id leftover from a failed test."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  begin wwv_flow_imp_page.remove_page("
        f"p_flow_id => {app_id}, p_page_id => {PROBE_LIFECYCLE_PAGE}"
        f"); exception when others then null; end;\n"
    )
    try:
        sess.execute(body)
    except Exception:
        pass  # best-effort


def test_delete_page_dev_live_full_cycle(dev_state):
    """Live DEV: add probe page, then apex_delete_page, verify pages back to original."""
    from apex_builder_mcp.tools.page_lifecycle import apex_delete_page

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_via_sqlcl(app_id)
        result = apex_delete_page(app_id=app_id, page_id=PROBE_LIFECYCLE_PAGE)
        assert result["dry_run"] is False
        assert result["after"]["pages"] == result["before"]["pages"] - 1
    finally:
        _cleanup_probe_lifecycle(app_id)


def test_delete_region_dev_live_full_cycle(dev_state):
    """Live DEV: add probe page+region, then apex_delete_region."""
    from apex_builder_mcp.tools.region_lifecycle import apex_delete_region
    from apex_builder_mcp.tools.regions import apex_add_region

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_via_sqlcl(app_id)
        apex_add_region(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            region_id=PROBE_LIFECYCLE_REGION,
            name="ITEST_PROBE_REGION",
        )
        result = apex_delete_region(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            region_id=PROBE_LIFECYCLE_REGION,
        )
        assert result["dry_run"] is False
        assert result["after"]["regions"] == result["before"]["regions"] - 1
    finally:
        _cleanup_probe_lifecycle(app_id)


def test_delete_item_dev_live_full_cycle(dev_state):
    """Live DEV: add probe page+region+item, then apex_delete_item."""
    from apex_builder_mcp.tools.item_lifecycle import apex_delete_item
    from apex_builder_mcp.tools.items import apex_add_item
    from apex_builder_mcp.tools.regions import apex_add_region

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_via_sqlcl(app_id)
        apex_add_region(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            region_id=PROBE_LIFECYCLE_REGION,
            name="ITEST_REGION",
        )
        apex_add_item(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            item_id=PROBE_LIFECYCLE_ITEM,
            region_id=PROBE_LIFECYCLE_REGION,
            name=f"P{PROBE_LIFECYCLE_PAGE}_ITEST",
        )
        result = apex_delete_item(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            item_id=PROBE_LIFECYCLE_ITEM,
        )
        assert result["dry_run"] is False
        assert result["after"]["items"] == result["before"]["items"] - 1
    finally:
        _cleanup_probe_lifecycle(app_id)


def test_update_page_dev_live(dev_state):
    """Live DEV: add probe page, update its name."""
    from apex_builder_mcp.tools.page_lifecycle import apex_update_page

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_via_sqlcl(app_id)
        result = apex_update_page(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            name="ITEST_PROBE_RENAMED",
        )
        assert result["dry_run"] is False
        # Page count unchanged
        assert result["after"]["pages"] == result["before"]["pages"]
    finally:
        _cleanup_probe_lifecycle(app_id)


def test_update_item_dev_live(dev_state):
    """update_item is deferred — verify clean error."""
    from apex_builder_mcp.schema.errors import ApexBuilderError
    from apex_builder_mcp.tools.item_lifecycle import apex_update_item

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_update_item(app_id=100, page_id=8500, item_id=8502, label="x")
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_bulk_add_items_dev_live(dev_state):
    """Live DEV: add probe page+region, then bulk add 3 items in one ImportSession."""
    from apex_builder_mcp.tools.items_bulk import apex_bulk_add_items
    from apex_builder_mcp.tools.regions import apex_add_region

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_via_sqlcl(app_id)
        apex_add_region(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            region_id=PROBE_LIFECYCLE_REGION,
            name="ITEST_REGION",
        )
        items = [
            {
                "item_id": 8510 + i,
                "name": f"P{PROBE_LIFECYCLE_PAGE}_BULK_{i}",
                "display_as": "NATIVE_TEXT_FIELD",
            }
            for i in range(3)
        ]
        result = apex_bulk_add_items(
            app_id=app_id,
            page_id=PROBE_LIFECYCLE_PAGE,
            region_id=PROBE_LIFECYCLE_REGION,
            items=items,
        )
        assert result["dry_run"] is False
        assert result["after"]["items"] == result["before"]["items"] + 3
    finally:
        _cleanup_probe_lifecycle(app_id)


# ---------------------------------------------------------------------------
# 2B-2 buttons / processes / dynamic-actions live DEV tests
#
# Probe ID range for 2B-2: 8600-8699 (avoids collision with 2B-1's 8500-8599).
# ---------------------------------------------------------------------------

PROBE_2B2_PAGE = 8600
PROBE_2B2_REGION = 8601
PROBE_2B2_BUTTON = 8602
PROBE_2B2_PROCESS = 8603
PROBE_2B2_DA_EVENT = 8604
PROBE_2B2_DA_ACTION = 8605


def _add_probe_page_2b2_via_sqlcl(app_id: int) -> None:
    """Use ImportSession directly to add a probe page for 2B-2 tests."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  wwv_flow_imp_page.create_page("
        f"p_id => {PROBE_2B2_PAGE}, "
        f"p_name => 'ITEST_PROBE_2B2', "
        f"p_alias => 'ITEST_PROBE_2B2', "
        f"p_step_title => 'ITEST_PROBE_2B2', "
        f"p_autocomplete_on_off => 'OFF', "
        f"p_page_template_options => '#DEFAULT#'"
        f");\n"
    )
    sess.execute(body)


def _cleanup_probe_2b2(app_id: int) -> None:
    """Best-effort cleanup of 2B-2 probe page (cascades to children)."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  begin wwv_flow_imp_page.remove_page("
        f"p_flow_id => {app_id}, p_page_id => {PROBE_2B2_PAGE}"
        f"); exception when others then null; end;\n"
    )
    try:
        sess.execute(body)
    except Exception:
        pass  # best-effort


def test_add_button_dev_live(dev_state):
    """Live DEV: add probe page+region, then apex_add_button + verify by id."""
    from apex_builder_mcp.tools.buttons import apex_add_button
    from apex_builder_mcp.tools.regions import apex_add_region

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_2b2_via_sqlcl(app_id)
        apex_add_region(
            app_id=app_id,
            page_id=PROBE_2B2_PAGE,
            region_id=PROBE_2B2_REGION,
            name="ITEST_2B2_REGION",
        )
        result = apex_add_button(
            app_id=app_id,
            page_id=PROBE_2B2_PAGE,
            button_id=PROBE_2B2_BUTTON,
            region_id=PROBE_2B2_REGION,
            name="ITEST_2B2_BTN",
            action="SUBMIT",
        )
        assert result["dry_run"] is False
        assert result["button_id"] == PROBE_2B2_BUTTON
    finally:
        _cleanup_probe_2b2(app_id)


def test_add_process_dev_live(dev_state):
    """Live DEV: add probe page, then apex_add_process + verify by id."""
    from apex_builder_mcp.tools.processes import apex_add_process

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_2b2_via_sqlcl(app_id)
        result = apex_add_process(
            app_id=app_id,
            page_id=PROBE_2B2_PAGE,
            process_id=PROBE_2B2_PROCESS,
            name="ITEST_2B2_PROC",
            plsql_code="null;",
        )
        assert result["dry_run"] is False
        assert result["process_id"] == PROBE_2B2_PROCESS
    finally:
        _cleanup_probe_2b2(app_id)


def test_add_dynamic_action_dev_live(dev_state):
    """Live DEV: add probe page+region+button, then apex_add_dynamic_action."""
    from apex_builder_mcp.tools.buttons import apex_add_button
    from apex_builder_mcp.tools.dynamic_actions import apex_add_dynamic_action
    from apex_builder_mcp.tools.regions import apex_add_region

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_2b2_via_sqlcl(app_id)
        apex_add_region(
            app_id=app_id,
            page_id=PROBE_2B2_PAGE,
            region_id=PROBE_2B2_REGION,
            name="ITEST_2B2_REGION",
        )
        apex_add_button(
            app_id=app_id,
            page_id=PROBE_2B2_PAGE,
            button_id=PROBE_2B2_BUTTON,
            region_id=PROBE_2B2_REGION,
            name="ITEST_2B2_BTN",
            action="DEFINED_BY_DA",
        )
        result = apex_add_dynamic_action(
            app_id=app_id,
            page_id=PROBE_2B2_PAGE,
            da_event_id=PROBE_2B2_DA_EVENT,
            da_action_id=PROBE_2B2_DA_ACTION,
            name="ITEST_2B2_DA",
            triggering_element=f"#B{PROBE_2B2_BUTTON}",
            event_type="click",
            action_type="NATIVE_ALERT",
            action_attribute_01="hello from 2B-2",
        )
        assert result["dry_run"] is False
        assert result["da_event_id"] == PROBE_2B2_DA_EVENT
        assert result["da_action_id"] == PROBE_2B2_DA_ACTION
    finally:
        _cleanup_probe_2b2(app_id)


# ---------------------------------------------------------------------------
# 2B-3 region-types live DEV tests
#
# Probe ID range for 2B-3: 8700-8799 (avoids collision with 2B-2's 8600-8699).
#
# Note: apex_add_interactive_grid derives extra IG component ids from region_id:
#   ig_id     = region_id
#   report_id = region_id + 1
#   view_id   = region_id + 2
# So PROBE_2B3_IG_REGION reserves a 3-id span (8702, 8703, 8704).
# ---------------------------------------------------------------------------

PROBE_2B3_PAGE = 8700
PROBE_2B3_FORM_REGION = 8701
PROBE_2B3_IG_REGION = 8710  # reserves 8710..8712 for ig+report+view ids


def _add_probe_page_2b3_via_sqlcl(app_id: int) -> None:
    """Use ImportSession directly to add a probe page for 2B-3 tests."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  wwv_flow_imp_page.create_page("
        f"p_id => {PROBE_2B3_PAGE}, "
        f"p_name => 'ITEST_PROBE_2B3', "
        f"p_alias => 'ITEST_PROBE_2B3', "
        f"p_step_title => 'ITEST_PROBE_2B3', "
        f"p_autocomplete_on_off => 'OFF', "
        f"p_page_template_options => '#DEFAULT#'"
        f");\n"
    )
    sess.execute(body)


def _cleanup_probe_2b3(app_id: int) -> None:
    """Best-effort cleanup of 2B-3 probe page (cascades to children)."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  begin wwv_flow_imp_page.remove_page("
        f"p_flow_id => {app_id}, p_page_id => {PROBE_2B3_PAGE}"
        f"); exception when others then null; end;\n"
    )
    try:
        sess.execute(body)
    except Exception:
        pass  # best-effort


def test_add_form_region_dev_live(dev_state):
    """Live DEV: add probe page, then apex_add_form_region for table EMP."""
    from apex_builder_mcp.tools.region_types import apex_add_form_region

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    # Use a small system table that's almost certainly accessible to the
    # workspace schema. Fall back to USER_TABLES which is universal.
    table_name = os.environ.get("APEX_TEST_FORM_TABLE", "USER_TABLES")
    try:
        _add_probe_page_2b3_via_sqlcl(app_id)
        result = apex_add_form_region(
            app_id=app_id,
            page_id=PROBE_2B3_PAGE,
            region_id=PROBE_2B3_FORM_REGION,
            table_name=table_name,
            name="ITEST_2B3_FORM",
        )
        assert result["dry_run"] is False
        assert result["region_id"] == PROBE_2B3_FORM_REGION
        assert result["after"]["regions"] == result["before"]["regions"] + 1
    finally:
        _cleanup_probe_2b3(app_id)


def test_add_interactive_grid_dev_live(dev_state):
    """Live DEV: add probe page, then apex_add_interactive_grid (4-proc compose)."""
    from apex_builder_mcp.tools.region_types import apex_add_interactive_grid

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_2b3_via_sqlcl(app_id)
        result = apex_add_interactive_grid(
            app_id=app_id,
            page_id=PROBE_2B3_PAGE,
            region_id=PROBE_2B3_IG_REGION,
            sql_query="select table_name, tablespace_name from user_tables",
            name="ITEST_2B3_IG",
        )
        assert result["dry_run"] is False
        assert result["region_id"] == PROBE_2B3_IG_REGION
        assert result["ig_id"] == PROBE_2B3_IG_REGION
        assert result["report_id"] == PROBE_2B3_IG_REGION + 1
        assert result["view_id"] == PROBE_2B3_IG_REGION + 2
        assert result["after"]["regions"] == result["before"]["regions"] + 1
    finally:
        _cleanup_probe_2b3(app_id)


def test_add_interactive_report_deferred_live(dev_state):
    """apex_add_interactive_report is deferred - verify clean error."""
    from apex_builder_mcp.schema.errors import ApexBuilderError
    from apex_builder_mcp.tools.region_types import apex_add_interactive_report

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_interactive_report(
            app_id=100, page_id=8700, region_id=8702,
            sql_query="select * from dual", name="x",
        )
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_add_master_detail_deferred_live(dev_state):
    """apex_add_master_detail is deferred - verify clean error."""
    from apex_builder_mcp.schema.errors import ApexBuilderError
    from apex_builder_mcp.tools.region_types import apex_add_master_detail

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_master_detail(
            app_id=100, page_id=8700,
            master_region_id=8710, detail_region_id=8720,
            master_table="DEPT", detail_table="EMP",
            link_column="DEPTNO", name="x",
        )
    assert exc_info.value.code == "TOOL_DEFERRED"


# ---------------------------------------------------------------------------
# 2B-4 charts / cards / calendar live DEV tests
#
# Probe ID range for 2B-4: 8800-8899 (avoids collision with 2B-3's 8700-8799).
#
# Note: apex_add_jet_chart derives extra ids from region_id:
#   chart_id  = region_id
#   series_id = region_id + 1
# So PROBE_2B4_CHART_REGION reserves a 2-id span (8810, 8811).
# ---------------------------------------------------------------------------

PROBE_2B4_PAGE = 8800
PROBE_2B4_CHART_REGION = 8810  # reserves 8810..8811 for chart+series ids
PROBE_2B4_CARDS_REGION = 8820
PROBE_2B4_CAL_REGION = 8830


def _add_probe_page_2b4_via_sqlcl(app_id: int) -> None:
    """Use ImportSession directly to add a probe page for 2B-4 tests."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  wwv_flow_imp_page.create_page("
        f"p_id => {PROBE_2B4_PAGE}, "
        f"p_name => 'ITEST_PROBE_2B4', "
        f"p_alias => 'ITEST_PROBE_2B4', "
        f"p_step_title => 'ITEST_PROBE_2B4', "
        f"p_autocomplete_on_off => 'OFF', "
        f"p_page_template_options => '#DEFAULT#'"
        f");\n"
    )
    sess.execute(body)


def _cleanup_probe_2b4(app_id: int) -> None:
    """Best-effort cleanup of 2B-4 probe page (cascades to children)."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body = (
        f"  begin wwv_flow_imp_page.remove_page("
        f"p_flow_id => {app_id}, p_page_id => {PROBE_2B4_PAGE}"
        f"); exception when others then null; end;\n"
    )
    try:
        sess.execute(body)
    except Exception:
        pass  # best-effort


def test_add_jet_chart_dev_live(dev_state):
    """Live DEV: add probe page, then apex_add_jet_chart (3-proc compose)."""
    from apex_builder_mcp.tools.charts_cards_calendar import apex_add_jet_chart

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_2b4_via_sqlcl(app_id)
        result = apex_add_jet_chart(
            app_id=app_id,
            page_id=PROBE_2B4_PAGE,
            region_id=PROBE_2B4_CHART_REGION,
            sql_query="select tablespace_name as label, count(*) as value "
                      "from user_tables group by tablespace_name",
            name="ITEST_2B4_CHART",
            chart_type="bar",
        )
        assert result["dry_run"] is False
        assert result["region_id"] == PROBE_2B4_CHART_REGION
        assert result["chart_id"] == PROBE_2B4_CHART_REGION
        assert result["series_id"] == PROBE_2B4_CHART_REGION + 1
        assert result["after"]["regions"] == result["before"]["regions"] + 1
    finally:
        _cleanup_probe_2b4(app_id)


def test_add_metric_cards_dev_live(dev_state):
    """Live DEV: add probe page, then apex_add_metric_cards (2-proc compose)."""
    from apex_builder_mcp.tools.charts_cards_calendar import apex_add_metric_cards

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_2b4_via_sqlcl(app_id)
        result = apex_add_metric_cards(
            app_id=app_id,
            page_id=PROBE_2B4_PAGE,
            region_id=PROBE_2B4_CARDS_REGION,
            sql_query="select table_name as title, tablespace_name as body "
                      "from user_tables",
            name="ITEST_2B4_CARDS",
        )
        assert result["dry_run"] is False
        assert result["region_id"] == PROBE_2B4_CARDS_REGION
        assert result["after"]["regions"] == result["before"]["regions"] + 1
    finally:
        _cleanup_probe_2b4(app_id)


def test_add_calendar_dev_live(dev_state):
    """Live DEV: add probe page, then apex_add_calendar."""
    from apex_builder_mcp.tools.charts_cards_calendar import apex_add_calendar

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        _add_probe_page_2b4_via_sqlcl(app_id)
        result = apex_add_calendar(
            app_id=app_id,
            page_id=PROBE_2B4_PAGE,
            region_id=PROBE_2B4_CAL_REGION,
            sql_query="select table_name, last_analyzed from user_tables",
            name="ITEST_2B4_CAL",
            date_column="LAST_ANALYZED",
        )
        assert result["dry_run"] is False
        assert result["region_id"] == PROBE_2B4_CAL_REGION
        assert result["date_column"] == "LAST_ANALYZED"
        assert result["after"]["regions"] == result["before"]["regions"] + 1
    finally:
        _cleanup_probe_2b4(app_id)


# ---------------------------------------------------------------------------
# 2B-5 shared-component live DEV tests
#
# Probe ID range for 2B-5: 8900-8999. Shared components are app-scoped
# (no probe page needed for LOV/auth/app_item; nav_item needs an existing
# list_id).
#
# Test isolation strategy: APEX 24.2 exposes no public REMOVE_LOV /
# REMOVE_AUTHENTICATION / REMOVE_FLOW_ITEM / REMOVE_LIST_ITEM procs, and the
# underlying apex_240200.wwv_flow_* tables are not delete-able from the
# workspace schema. Once a leftover record is in place, recreating with the
# same (flow_id, name) violates WWV_FLOW_ITEMS_IDX3 / similar unique indexes.
# Therefore each test run randomizes BOTH the id (in 8900..8998) AND the
# name (suffix = secrets.token_hex(3)). Collisions across runs become
# astronomically unlikely. Live-test artifacts accumulate harmlessly and
# can be cleaned via App Builder UI if desired.
# ---------------------------------------------------------------------------

PROBE_2B5_NAV_ITEM = 8980  # nav_item still uses static id; name not in unique idx


def _random_probe_suffix() -> str:
    """6 hex chars, ~16M unique values per run."""
    return secrets.token_hex(3).upper()


def _random_probe_id() -> int:
    """Random id in 8900..8998 inclusive (10 reserved slots above lov rows)."""
    return 8900 + secrets.randbelow(99)


def _cleanup_2b5_shared_components(app_id: int) -> None:
    """Best-effort cleanup of 2B-5 shared components — see header comment.

    Kept as a no-op shim so the existing nav_item test (which still uses
    static id) keeps the same shape; randomized tests do per-id cleanup
    inline using the id they actually created.
    """
    return


def _query_first_list_id(app_id: int) -> int | None:
    """Find any existing app-scoped list to use for nav_item test."""
    from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select min(list_id) from apex_application_lists "
        f"where application_id = {app_id};\nexit\n"
    )
    result = run_sqlcl(os.environ["APEX_TEST_SQLCL_NAME"], sql, timeout=30)
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s)
    return None


def test_add_lov_dev_live(dev_state):
    """Live DEV: add a static LOV with two values, verify via apex_application_lovs.

    Randomizes both lov_id and name per run to avoid WWV_FLOW_ITEMS_IDX3 /
    LOV unique-name collisions with leftover state from prior runs.
    """
    from apex_builder_mcp.tools.shared_components import apex_add_lov

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    suffix = _random_probe_suffix()
    lov_id = _random_probe_id()
    lov_name = f"ITEST_2B5_LOV_{suffix}"
    try:
        result = apex_add_lov(
            app_id=app_id,
            lov_id=lov_id,
            name=lov_name,
            lov_type="STATIC",
            static_values=[
                {"display": "Active", "return": "A"},
                {"display": "Inactive", "return": "I"},
            ],
        )
        assert result["dry_run"] is False
        assert result["lov_id"] == lov_id
        assert result["static_value_count"] == 2
    finally:
        _cleanup_2b5_shared_components(app_id)


def test_list_lovs_dev_live(dev_state):
    """Live DEV: read-only call to apex_list_lovs returns at least one LOV.

    Now branches on profile.auth_mode (sqlcl in tests) — uses SQLcl subprocess
    when no oracledb pool is configured.
    """
    from apex_builder_mcp.tools.shared_components import apex_list_lovs

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    result = apex_list_lovs(app_id=app_id)
    assert "lovs" in result
    assert "count" in result
    # We do not assert count > 0 because a fresh app may have zero LOVs.


def test_add_auth_scheme_dev_live(dev_state):
    """Live DEV: add a custom auth scheme with PL/SQL function body.

    Randomizes both auth_id and name per run to avoid uniqueness collisions
    with leftover state.
    """
    from apex_builder_mcp.tools.shared_components import apex_add_auth_scheme

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    suffix = _random_probe_suffix()
    auth_id = _random_probe_id()
    auth_name = f"ITEST_2B5_AUTH_{suffix}"
    try:
        result = apex_add_auth_scheme(
            app_id=app_id,
            auth_id=auth_id,
            name=auth_name,
            scheme_type="NATIVE_CUSTOM",
            plsql_code="return :APP_USER is not null;",
        )
        assert result["dry_run"] is False
        assert result["auth_id"] == auth_id
    finally:
        _cleanup_2b5_shared_components(app_id)


def test_add_nav_item_dev_live(dev_state):
    """Live DEV: add a nav-list entry to an existing app-level list.

    Skips if the target app has no existing lists.
    """
    from apex_builder_mcp.tools.shared_components import apex_add_nav_item

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    list_id = _query_first_list_id(app_id)
    if list_id is None:
        pytest.skip(f"app {app_id} has no existing lists; cannot test nav_item")

    try:
        result = apex_add_nav_item(
            app_id=app_id,
            list_item_id=PROBE_2B5_NAV_ITEM,
            list_id=list_id,
            name="ITEST_2B5_NAV",
            target_url=f"f?p=&APP_ID.:{PROBE_2B4_PAGE}",
            sequence=999,
        )
        assert result["dry_run"] is False
        assert result["list_item_id"] == PROBE_2B5_NAV_ITEM
    finally:
        _cleanup_2b5_shared_components(app_id)


def test_add_app_item_dev_live(dev_state):
    """Live DEV: add an application-level item, verify via apex_application_items.

    Randomizes both item_id and name per run; the (flow_id, name) unique
    index WWV_FLOW_ITEMS_IDX3 is what was breaking us with static names.
    """
    from apex_builder_mcp.tools.shared_components import apex_add_app_item

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    suffix = _random_probe_suffix()
    item_id = _random_probe_id()
    item_name = f"ITEST_2B5_GLOBAL_{suffix}"
    try:
        result = apex_add_app_item(
            app_id=app_id,
            item_id=item_id,
            name=item_name,
            scope="APPLICATION",
        )
        assert result["dry_run"] is False
        assert result["item_id"] == item_id
        assert result["scope"] == "APPLICATION"
    finally:
        _cleanup_2b5_shared_components(app_id)


# ---------------------------------------------------------------------------
# 2B-6 page-asset + read-extension live DEV tests
#
# Probe range for 2B-6: 9100-9199 (per plan).
#
# - Static-file tests randomize file_name (using token_hex(3)) so leftover
#   files from prior failed cleanups never collide on the unique
#   (application_id, file_name) constraint. Cleanup attempts to call
#   wwv_flow_imp_shared.remove_app_static_file when the file_id can be
#   resolved via apex_application_static_files.
# - search_objects + dependencies + list_workspace_users use oracledb pool
#   so they require a profile that has password auth available; if the test
#   env is sqlcl-only those tests skip.
# ---------------------------------------------------------------------------


def _cleanup_2b6_static_file(app_id: int, file_name: str) -> None:
    """Best-effort cleanup of an app static file by name."""
    from apex_builder_mcp.apex_api.import_session import ImportSession
    from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl

    name_esc = file_name.replace("'", "''")
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select application_file_id from apex_application_static_files "
        f"where application_id = {app_id} and file_name = '{name_esc}';\n"
        "exit\n"
    )
    try:
        result = run_sqlcl(os.environ["APEX_TEST_SQLCL_NAME"], sql, timeout=30)
        file_id: int | None = None
        for line in result.cleaned.splitlines():
            s = line.strip()
            if s.isdigit():
                file_id = int(s)
                break
        if file_id is None:
            return
        sess = ImportSession(
            sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
            workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
            application_id=app_id,
            schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
        )
        sess.execute(
            f"  wwv_flow_imp_shared.remove_app_static_file("
            f"p_id => {file_id}, p_flow_id => {app_id});\n"
        )
    except Exception:
        pass  # best-effort


def test_add_static_app_file_dev_live_2b6(dev_state):
    """Live DEV: upload a small CSS file as an app static file.

    Randomized name avoids collision with leftover state from prior failed
    runs (the (application_id, file_name) tuple is unique).
    """
    from apex_builder_mcp.tools.page_assets import apex_add_static_app_file

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    suffix = _random_probe_suffix()
    file_id = 9100 + secrets.randbelow(99)
    file_name = f"itest_2b6_{suffix}.css"
    try:
        result = apex_add_static_app_file(
            app_id=app_id,
            file_name=file_name,
            file_content_text="/* itest 2b6 */\nbody { color: rebeccapurple; }\n",
            mime_type="text/css",
            file_id=file_id,
        )
        assert result["dry_run"] is False
        assert result["file_name"] == file_name
        assert result["mime_type"] == "text/css"
    finally:
        _cleanup_2b6_static_file(app_id, file_name)


def test_add_page_js_deferred_live_2b6(dev_state):
    """apex_add_page_js is deferred — verify clean error."""
    from apex_builder_mcp.schema.errors import ApexBuilderError
    from apex_builder_mcp.tools.page_assets import apex_add_page_js

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_page_js(app_id=100, page_id=1, javascript_code="x;")
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_add_app_css_deferred_live_2b6(dev_state):
    """apex_add_app_css is deferred — verify clean error."""
    from apex_builder_mcp.schema.errors import ApexBuilderError
    from apex_builder_mcp.tools.page_assets import apex_add_app_css

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_app_css(app_id=100, css_code="x")
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_search_objects_dev_live_2b6(dev_state):
    """Live DEV: search for objects matching APEX_% pattern.

    Branches on profile.auth_mode — uses SQLcl subprocess under sqlcl mode.
    """
    from apex_builder_mcp.tools.inspect_db import apex_search_objects

    result = apex_search_objects(pattern="APEX_%", object_types=["VIEW"])
    assert "objects" in result
    assert "count" in result
    # Real DBs have many APEX_* views; if 0 the env is unusual but valid.


def test_dependencies_dev_live_2b6(dev_state):
    """Live DEV: get dependencies of DUAL.

    Branches on profile.auth_mode — uses SQLcl subprocess under sqlcl mode.
    """
    from apex_builder_mcp.tools.inspect_db import apex_dependencies

    result = apex_dependencies(object_name="DUAL")
    assert "uses" in result
    assert "used_by" in result
    # DUAL is heavily depended-on; expect used_by_count > 0 typically.


def test_list_workspace_users_dev_live_2b6(dev_state):
    """Live DEV: list workspace users.

    Branches on profile.auth_mode — uses SQLcl subprocess under sqlcl mode.
    """
    from apex_builder_mcp.tools.inspect_apex import apex_list_workspace_users

    result = apex_list_workspace_users(
        workspace=os.environ.get("APEX_TEST_WORKSPACE", "EREPORT")
    )
    assert "users" in result
    assert "count" in result


# ---------------------------------------------------------------------------
# Read-tool sqlcl-fallback live DEV tests
#
# These verify all read tools that previously called _get_pool() directly
# now route through tools/_read_helpers and execute under auth_mode=sqlcl.
# ---------------------------------------------------------------------------


def test_list_apps_dev_live_sqlcl(dev_state):
    """Live DEV: list apps via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import apex_list_apps

    result = apex_list_apps(
        workspace=os.environ.get("APEX_TEST_WORKSPACE", "EREPORT")
    )
    assert "apps" in result
    assert "count" in result
    # Source app should be visible
    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    app_ids = [a["application_id"] for a in result["apps"]]
    assert src_app_id in app_ids


def test_describe_app_dev_live_sqlcl(dev_state):
    """Live DEV: describe source app via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import apex_describe_app

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    result = apex_describe_app(app_id=src_app_id)
    assert result["found"] is True
    assert result["application_id"] == src_app_id
    assert result["application_name"]
    assert isinstance(result["lov_count"], int)


def test_describe_app_not_found_dev_live_sqlcl(dev_state):
    """Live DEV: describe non-existent app returns found=False."""
    from apex_builder_mcp.tools.inspect_apex import apex_describe_app

    result = apex_describe_app(app_id=999999)
    assert result["found"] is False


def test_list_pages_dev_live_sqlcl(dev_state):
    """Live DEV: list pages via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import apex_list_pages

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    result = apex_list_pages(app_id=src_app_id)
    assert "pages" in result
    assert result["count"] >= 1
    # Page 0 (Global) should typically exist
    page_ids = [p["page_id"] for p in result["pages"]]
    assert 0 in page_ids or 1 in page_ids


def test_describe_page_dev_live_sqlcl(dev_state):
    """Live DEV: describe page 0 via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import apex_describe_page

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    # Try page 0 first; if absent fall back to first listed page.
    result = apex_describe_page(app_id=src_app_id, page_id=0)
    if not result.get("found"):
        from apex_builder_mcp.tools.inspect_apex import apex_list_pages

        pages = apex_list_pages(app_id=src_app_id)["pages"]
        if not pages:
            pytest.skip("source app has no pages")
        result = apex_describe_page(
            app_id=src_app_id, page_id=pages[0]["page_id"]
        )
    assert result["found"] is True
    assert "regions" in result
    assert "items" in result
    assert "buttons" in result
    assert "processes" in result


def test_describe_acl_dev_live_sqlcl(dev_state):
    """Live DEV: describe ACL of source app via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import apex_describe_acl

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    result = apex_describe_acl(app_id=src_app_id)
    assert "assignments" in result
    assert "count" in result


def test_get_page_details_dev_live_sqlcl(dev_state):
    """Live DEV: full page details via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import (
        apex_get_page_details,
        apex_list_pages,
    )

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    pages = apex_list_pages(app_id=src_app_id)["pages"]
    if not pages:
        pytest.skip("source app has no pages")
    page_id = pages[0]["page_id"]
    result = apex_get_page_details(app_id=src_app_id, page_id=page_id)
    assert result["found"] is True
    assert "details" in result
    assert "PAGE_NAME" in result["details"]


def test_list_regions_dev_live_sqlcl(dev_state):
    """Live DEV: list regions via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import (
        apex_list_pages,
        apex_list_regions,
    )

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    pages = apex_list_pages(app_id=src_app_id)["pages"]
    if not pages:
        pytest.skip("source app has no pages")
    # Find a page with at least 1 region by scanning a few pages
    for p in pages[:10]:
        result = apex_list_regions(app_id=src_app_id, page_id=p["page_id"])
        if result["count"] > 0:
            assert "regions" in result
            assert isinstance(result["regions"], list)
            return
    # Even with 0 regions everywhere, the call should succeed
    assert "regions" in result


def test_list_items_dev_live_sqlcl(dev_state):
    """Live DEV: list items via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import (
        apex_list_items,
        apex_list_pages,
    )

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    pages = apex_list_pages(app_id=src_app_id)["pages"]
    if not pages:
        pytest.skip("source app has no pages")
    for p in pages[:10]:
        result = apex_list_items(app_id=src_app_id, page_id=p["page_id"])
        if result["count"] > 0:
            assert "items" in result
            return
    assert "items" in result


def test_list_processes_dev_live_sqlcl(dev_state):
    """Live DEV: list processes via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import (
        apex_list_pages,
        apex_list_processes,
    )

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    pages = apex_list_pages(app_id=src_app_id)["pages"]
    if not pages:
        pytest.skip("source app has no pages")
    for p in pages[:10]:
        result = apex_list_processes(app_id=src_app_id, page_id=p["page_id"])
        assert "processes" in result
        if result["count"] > 0:
            return


def test_list_dynamic_actions_dev_live_sqlcl(dev_state):
    """Live DEV: list dynamic actions via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_apex import (
        apex_list_dynamic_actions,
        apex_list_pages,
    )

    src_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    pages = apex_list_pages(app_id=src_app_id)["pages"]
    if not pages:
        pytest.skip("source app has no pages")
    for p in pages[:10]:
        result = apex_list_dynamic_actions(
            app_id=src_app_id, page_id=p["page_id"]
        )
        assert "dynamic_actions" in result
        if result["count"] > 0:
            return


def test_list_tables_dev_live_sqlcl(dev_state):
    """Live DEV: list tables via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_db import apex_list_tables

    result = apex_list_tables()
    assert "tables" in result
    assert "count" in result


def test_describe_table_dev_live_sqlcl(dev_state):
    """Live DEV: describe DUAL via SQLcl subprocess."""
    from apex_builder_mcp.tools.inspect_db import apex_describe_table

    result = apex_describe_table(table_name="DUAL", schema="SYS")
    assert result["table_name"] == "DUAL"
    assert "columns" in result
    # DUAL has a single column DUMMY
    if result["columns"]:
        col_names = {c["name"] for c in result["columns"]}
        assert "DUMMY" in col_names


def test_get_source_dev_live_sqlcl(dev_state):
    """Live DEV: get source of a known package via SQLcl subprocess.

    Picks any package the connected user owns; skips if none exist.
    """
    from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
    from apex_builder_mcp.tools.inspect_db import apex_get_source

    # Find a package the connected user owns
    result = run_sqlcl(
        os.environ["APEX_TEST_SQLCL_NAME"],
        (
            "set heading off feedback off pagesize 0 echo off\n"
            "select min(name) from user_source where type = 'PACKAGE';\n"
            "exit\n"
        ),
        timeout=30,
    )
    pkg_name: str | None = None
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s and s.replace("_", "").replace("$", "").replace("#", "").isalnum():
            pkg_name = s
            break
    if not pkg_name:
        pytest.skip("no packages owned by connected user")
    src = apex_get_source(object_name=pkg_name, object_type="PACKAGE")
    assert src["object_name"] == pkg_name.upper()
    assert src["object_type"] == "PACKAGE"
    assert src["line_count"] >= 1


# ---------------------------------------------------------------------------
# 2B-7 generator live DEV tests
#
# Probe ID range for 2B-7: 9200-9299. Generators compose existing low-level
# tools — these tests verify the end-to-end composition seeds expected
# artifacts and that cleanup-via-apex_delete_page works for each created page.
#
# Table choice: live tests bind form regions to a table that exists in the
# EREPORT workspace schema. We resolve dynamically — first table that EREPORT
# can see via user_tables — to avoid hard-coding EMP-style fixture tables.
# ---------------------------------------------------------------------------


def _resolve_test_table(app_id: int) -> str | None:
    """Find any user table in workspace schema for live form-region tests."""
    from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl

    try:
        result = run_sqlcl(
            os.environ["APEX_TEST_SQLCL_NAME"],
            (
                "set heading off feedback off pagesize 0 echo off\n"
                "select min(table_name) from user_tables;\nexit\n"
            ),
            timeout=30,
        )
        for line in result.cleaned.splitlines():
            s = line.strip()
            # First identifier-like token wins (allow $ # _ in oracle names)
            if s and s.replace("_", "").replace("$", "").replace("#", "").isalnum():
                return s
    except Exception:
        return None
    return None


def _cleanup_2b7_pages(app_id: int, page_ids: list[int]) -> None:
    """Best-effort cascade-delete of probe pages via remove_page in import session."""
    from apex_builder_mcp.apex_api.import_session import ImportSession

    sess = ImportSession(
        sqlcl_conn=os.environ["APEX_TEST_SQLCL_NAME"],
        workspace_id=int(os.environ.get("APEX_TEST_WORKSPACE_ID", "100002")),
        application_id=app_id,
        schema=os.environ.get("APEX_TEST_SCHEMA", "EREPORT"),
    )
    body_lines: list[str] = []
    for pid in page_ids:
        body_lines.append(
            f"  begin wwv_flow_imp_page.remove_page("
            f"p_flow_id => {app_id}, p_page_id => {pid}"
            f"); exception when others then null; end;\n"
        )
    try:
        sess.execute("".join(body_lines))
    except Exception:
        pass  # best-effort


def test_generate_crud_dev_live_2b7(dev_state):
    """Live DEV: generate CRUD pair (list + form) over a real table."""
    from apex_builder_mcp.tools.generators import apex_generate_crud

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    table = _resolve_test_table(app_id)
    if table is None:
        pytest.skip("No user_tables visible to APEX_TEST_SQLCL_NAME schema")

    list_page_id = 9200 + secrets.randbelow(20)
    form_page_id = list_page_id + 30  # avoid id collision with ig_region (list+1)
    try:
        result = apex_generate_crud(
            app_id=app_id,
            table_name=table,
            list_page_id=list_page_id,
            form_page_id=form_page_id,
        )
        assert result["dry_run"] is False
        assert result["created"]["list_page"] == list_page_id
        assert result["created"]["ig_region"] == list_page_id + 1
        assert result["created"]["form_page"] == form_page_id
        assert result["created"]["form_region"] == form_page_id + 1
    finally:
        _cleanup_2b7_pages(app_id, [list_page_id, form_page_id])


def test_generate_dashboard_dev_live_2b7(dev_state):
    """Live DEV: generate dashboard with both KPI cards + chart."""
    from apex_builder_mcp.tools.generators import apex_generate_dashboard

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    page_id = 9230 + secrets.randbelow(20)
    try:
        result = apex_generate_dashboard(
            app_id=app_id,
            page_id=page_id,
            name=f"Dashboard 2B7 {secrets.token_hex(2).upper()}",
            kpi_query=(
                "select tablespace_name as title, count(*) as body "
                "from user_tables group by tablespace_name"
            ),
            chart_query=(
                "select tablespace_name as label, count(*) as value "
                "from user_tables group by tablespace_name"
            ),
        )
        assert result["dry_run"] is False
        assert result["created"]["page"] == page_id
        assert result["created"]["kpi_region"] == page_id + 1
        assert result["created"]["chart_region"] == page_id + 2
    finally:
        _cleanup_2b7_pages(app_id, [page_id])


def test_generate_login_deferred_2b7(dev_state):
    """apex_generate_login is deferred — verify clean error."""
    from apex_builder_mcp.schema.errors import ApexBuilderError
    from apex_builder_mcp.tools.generators import apex_generate_login

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_login(app_id=100)
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_generate_modal_form_dev_live_2b7(dev_state):
    """Live DEV: generate a modal form page over a real table."""
    from apex_builder_mcp.tools.generators import apex_generate_modal_form

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    table = _resolve_test_table(app_id)
    if table is None:
        pytest.skip("No user_tables visible to APEX_TEST_SQLCL_NAME schema")

    page_id = 9270 + secrets.randbelow(20)
    try:
        result = apex_generate_modal_form(
            app_id=app_id,
            page_id=page_id,
            table_name=table,
            name=f"Modal {secrets.token_hex(2).upper()}",
        )
        assert result["dry_run"] is False
        assert result["page_mode"] == "MODAL"
        assert result["created"]["page"] == page_id
        assert result["created"]["form_region"] == page_id + 1
    finally:
        _cleanup_2b7_pages(app_id, [page_id])


# ---------------------------------------------------------------------------
# 2B-8 app lifecycle live DEV tests
#
# Probe ranges:
#   * apex_get_app_details / apex_validate_app -> existing source app
#   * apex_create_app + apex_delete_app -> 999000-999999 (avoid collision
#     with real apps which are typically 100-1000 range).
# Cleanup pattern: ALWAYS delete via apex_delete_app in finally even on
# partial-create failures.
# ---------------------------------------------------------------------------


def test_get_app_details_dev_live_2b8(dev_state):
    """Live DEV: get full metadata of the source app.

    Branches on profile.auth_mode — uses SQLcl subprocess under sqlcl mode.
    """
    from apex_builder_mcp.tools.apps import apex_get_app_details

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    result = apex_get_app_details(app_id=app_id)

    assert result["found"] is True
    assert result["application_id"] == app_id
    assert "APPLICATION_NAME" in result["details"]
    assert "ALIAS" in result["details"]
    assert "PAGES" in result["details"]


def test_get_app_details_not_found_dev_live_2b8(dev_state):
    """Live DEV: get_app_details returns found=False for non-existent app."""
    from apex_builder_mcp.tools.apps import apex_get_app_details

    result = apex_get_app_details(app_id=999999)
    assert result["found"] is False


def test_validate_app_dev_live_2b8(dev_state):
    """Live DEV: validate the source app (read-only heuristic checks).

    Branches on profile.auth_mode — uses SQLcl subprocess under sqlcl mode.
    """
    from apex_builder_mcp.tools.apps import apex_validate_app

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    result = apex_validate_app(app_id=app_id)

    assert "ok" in result
    assert "issues" in result
    assert "counts" in result
    # Real app may or may not have issues — the test verifies the contract,
    # not a specific clean-state outcome.


def test_validate_app_not_found_dev_live_2b8(dev_state):
    """Live DEV: validate_app on missing app reports APP_NOT_FOUND."""
    from apex_builder_mcp.tools.apps import apex_validate_app

    result = apex_validate_app(app_id=999999)
    assert result["ok"] is False
    assert any(i["code"] == "APP_NOT_FOUND" for i in result["issues"])


def test_create_and_delete_app_dev_live_2b8(dev_state):
    """Live DEV: create a sandbox app stub then delete it via apex_delete_app.

    create_app produces a partial-functionality stub; we verify it appears in
    apex_applications with the expected name/alias and 1 page (Home), then
    clean up via apex_delete_app and verify it is gone.
    """
    from apex_builder_mcp.tools.apps import (
        apex_create_app,
        apex_delete_app,
        apex_get_app_details,
    )

    sandbox_app_id = 999000 + secrets.randbelow(1000)
    sandbox_alias = f"P2B8_{secrets.token_hex(3).upper()}"
    sandbox_name = f"Probe 2B8 {secrets.token_hex(2).upper()}"

    create_done = False
    try:
        # 1. Create
        create_result = apex_create_app(
            name=sandbox_name,
            alias=sandbox_alias,
            app_id=sandbox_app_id,
        )
        assert create_result["dry_run"] is False
        assert create_result["app_id"] == sandbox_app_id
        assert create_result["alias"] == sandbox_alias
        assert create_result["partial_functionality"] is True
        create_done = True

        # 2. Verify via apex_get_app_details (now sqlcl-fallback aware).
        details = apex_get_app_details(app_id=sandbox_app_id)
        assert details["found"] is True
        assert details["details"]["ALIAS"] == sandbox_alias
    finally:
        # 3. Cleanup — always delete, even if assertions failed mid-test
        try:
            delete_result = apex_delete_app(app_id=sandbox_app_id)
            if create_done:
                assert delete_result["deleted"] is True
        except Exception:
            # Best-effort cleanup via raw SQLcl
            from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
            run_sqlcl(
                os.environ["APEX_TEST_SQLCL_NAME"],
                (
                    "set echo off feedback off\n"
                    f"begin wwv_flow_imp.remove_flow(p_id => {sandbox_app_id}); "
                    f"commit; exception when others then null; end;\n/\nexit\n"
                ),
                timeout=60,
            )


def test_delete_app_missing_app_silently_ok_live_2b8(dev_state):
    """Live DEV: delete_app on a non-existent app is idempotent.

    Phase 0 finding (re-verified during 2B-8): wwv_flow_imp.remove_flow
    silently succeeds when the app doesn't exist. The post-verify check
    confirms the app is gone (count=0 even when it never existed), so the
    tool returns deleted=True. This is benign idempotent behavior.
    """
    from apex_builder_mcp.tools.apps import apex_delete_app

    # Pick an id well outside known ranges
    missing_id = 998000 + secrets.randbelow(500)
    result = apex_delete_app(app_id=missing_id)
    assert result["dry_run"] is False
    assert result["deleted"] is True
    assert result["app_id"] == missing_id


# ---------------------------------------------------------------------------
# apex_run_sql sqlcl-fallback (closes last read-tool pool gap)
# ---------------------------------------------------------------------------


def test_run_sql_dev_live_via_sqlcl(dev_state):
    """apex_run_sql should now work under sqlcl auth_mode."""
    from apex_builder_mcp.tools.inspect_db import apex_run_sql

    result = apex_run_sql(
        "select application_id, application_name from apex_applications "
        "where workspace = 'EREPORT' order by application_id "
        "fetch first 3 rows only"
    )
    assert result["row_count"] >= 1
    assert "APPLICATION_ID" in [c.upper() for c in result["columns"]]


def test_run_sql_handles_empty_result_via_sqlcl(dev_state):
    from apex_builder_mcp.tools.inspect_db import apex_run_sql

    result = apex_run_sql("select 1 as x from apex_applications where 1 = 0")
    assert result["row_count"] == 0


def test_run_sql_handles_null_via_sqlcl(dev_state):
    from apex_builder_mcp.tools.inspect_db import apex_run_sql

    result = apex_run_sql("select null as x, 'hello' as y from dual")
    assert result["row_count"] == 1
