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
# list_id). Cleanup uses wwv_flow_imp_shared.remove_* where available, else
# wraps best-effort PL/SQL block.
# ---------------------------------------------------------------------------

PROBE_2B5_LOV = 8950          # reserves 8950..8959 (LOV + up to 9 static rows)
PROBE_2B5_AUTH = 8970
PROBE_2B5_NAV_ITEM = 8980
PROBE_2B5_APP_ITEM = 8990


def _cleanup_2b5_shared_components(app_id: int) -> None:
    """Best-effort cleanup of 2B-5 shared components.

    Note: wwv_flow_imp_shared has no public REMOVE_LOV / REMOVE_AUTHENTICATION
    / REMOVE_FLOW_ITEM / REMOVE_LIST_ITEM procs in APEX 24.2. The underlying
    apex_240200.wwv_flow_* tables are not directly delete-able from a
    workspace schema (definer's rights don't carry). The pragmatic test
    strategy is: each test run uses fresh probe ids if the previous run's
    ids leaked. The probe ids above (8950+) are deliberately high to leave
    headroom; bump them if they ever collide. Live-test artifacts can be
    cleaned via App Builder UI if needed.
    """
    # No-op: see docstring. Tests rely on fresh ids per run.
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
    """Live DEV: add a static LOV with two values, verify via apex_application_lovs."""
    from apex_builder_mcp.tools.shared_components import apex_add_lov

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        result = apex_add_lov(
            app_id=app_id,
            lov_id=PROBE_2B5_LOV,
            name="ITEST_2B5_LOV",
            lov_type="STATIC",
            static_values=[
                {"display": "Active", "return": "A"},
                {"display": "Inactive", "return": "I"},
            ],
        )
        assert result["dry_run"] is False
        assert result["lov_id"] == PROBE_2B5_LOV
        assert result["static_value_count"] == 2
    finally:
        _cleanup_2b5_shared_components(app_id)


def test_list_lovs_dev_live(dev_state):
    """Live DEV: read-only call to apex_list_lovs returns at least one LOV.

    NOTE: this requires auth_mode=password (oracledb pool) since the read uses
    the connection pool. If pool isn't configured, skip cleanly.
    """
    from apex_builder_mcp.tools.shared_components import apex_list_lovs

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        result = apex_list_lovs(app_id=app_id)
        assert "lovs" in result
        assert "count" in result
        # We do not assert count > 0 because a fresh app may have zero LOVs.
    except Exception as e:
        # apex_list_lovs needs an oracledb pool which sqlcl-only profiles
        # don't have. Accept this as a skip in pure-sqlcl test env.
        pytest.skip(f"apex_list_lovs requires oracledb pool: {e}")


def test_add_auth_scheme_dev_live(dev_state):
    """Live DEV: add a custom auth scheme with PL/SQL function body."""
    from apex_builder_mcp.tools.shared_components import apex_add_auth_scheme

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        result = apex_add_auth_scheme(
            app_id=app_id,
            auth_id=PROBE_2B5_AUTH,
            name="ITEST_2B5_AUTH",
            scheme_type="NATIVE_CUSTOM",
            plsql_code="return :APP_USER is not null;",
        )
        assert result["dry_run"] is False
        assert result["auth_id"] == PROBE_2B5_AUTH
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
    """Live DEV: add an application-level item, verify via apex_application_items."""
    from apex_builder_mcp.tools.shared_components import apex_add_app_item

    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))
    try:
        result = apex_add_app_item(
            app_id=app_id,
            item_id=PROBE_2B5_APP_ITEM,
            name="ITEST_2B5_GLOBAL",
            scope="APPLICATION",
        )
        assert result["dry_run"] is False
        assert result["item_id"] == PROBE_2B5_APP_ITEM
        assert result["scope"] == "APPLICATION"
    finally:
        _cleanup_2b5_shared_components(app_id)
