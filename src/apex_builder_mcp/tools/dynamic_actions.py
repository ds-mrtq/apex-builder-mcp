"""apex_add_dynamic_action — DEV-only write tool wrapping
wwv_flow_imp_page.create_page_da_event + create_page_da_action.

A dynamic action requires TWO internal API calls in a single ImportSession:
  1. create_page_da_event   — when (event + triggering element)
  2. create_page_da_action  — then (action with attribute_01)

Verification: queries apex_application_page_da by dynamic_action_id (the
DA event id). expected_delta is {} since DAs are not tracked in
MetadataSnapshot.
"""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.apex_api.import_session import ImportSession
from apex_builder_mcp.audit.auto_export import refresh_export
from apex_builder_mcp.audit.post_write_verify import verify_post_fail
from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.guard.policy import PolicyContext, enforce_policy
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools._write_helpers import (
    query_metadata_snapshot,
    query_workspace_id,
)


def _verify_da_exists(
    profile: Profile, app_id: int, page_id: int, da_event_id: int
) -> bool:
    """Query apex_application_page_da to confirm the DA event was created."""
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select count(*) from apex_application_page_da "
        f"where application_id = {app_id} and page_id = {page_id} "
        f"and dynamic_action_id = {da_event_id};\nexit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    for line in result.stdout.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s) == 1
    return False


@apex_tool(name="apex_add_dynamic_action", category=Category.WRITE_CORE)
def apex_add_dynamic_action(
    app_id: int,
    page_id: int,
    da_event_id: int,
    da_action_id: int,
    name: str,
    triggering_element: str,
    event_type: str,
    action_type: str,
    action_attribute_01: str = "",
    sequence: int = 10,
) -> dict[str, Any]:
    """Add a dynamic action (event + action) via two wwv_flow_imp_page calls.

    DEV-only. TEST returns dry-run SQL preview. PROD rejects.
    Wraps both calls in a single wwv_flow_imp.import_begin/import_end block.

    Post-write verification: queries apex_application_page_da by da_event_id.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    # Escape single quotes for safe embedding in PL/SQL string literals.
    name_esc = name.replace("'", "''")
    trig_esc = triggering_element.replace("'", "''")
    event_esc = event_type.replace("'", "''")
    action_esc = action_type.replace("'", "''")
    attr_esc = action_attribute_01.replace("'", "''")

    plsql_body = f"""  wwv_flow_imp_page.create_page_da_event(
    p_id => {da_event_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_name => '{name_esc}',
    p_event_sequence => {sequence},
    p_bind_type => 'bind',
    p_bind_event_type => '{event_esc}',
    p_triggering_element_type => 'JQUERY_SELECTOR',
    p_triggering_element => '{trig_esc}'
  );
  wwv_flow_imp_page.create_page_da_action(
    p_id => {da_action_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_event_id => {da_event_id},
    p_event_result => 'TRUE',
    p_action_sequence => 10,
    p_execute_on_page_init => 'N',
    p_action => '{action_esc}',
    p_attribute_01 => '{attr_esc}'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_add_dynamic_action",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "da_event_id": da_event_id,
            "da_action_id": da_action_id,
            "sql_preview": (
                f"-- import_begin/import_end wrap for app {app_id}\n"
                f"-- body:\n{plsql_body}"
            ),
        }

    ws_id = query_workspace_id(profile, profile.workspace)
    before, alias = query_metadata_snapshot(profile, app_id)

    sess = ImportSession(
        sqlcl_conn=profile.sqlcl_name,
        workspace_id=ws_id,
        application_id=app_id,
        schema=profile.workspace,
    )
    try:
        sess.execute(plsql_body)
    except Exception as e:
        after_fail, _ = query_metadata_snapshot(profile, app_id)
        verify_post_fail(before, after_fail)
        raise ApexBuilderError(
            code="WRITE_EXEC_FAIL",
            message=f"apex_add_dynamic_action failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    if not _verify_da_exists(profile, app_id, page_id, da_event_id):
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"DA event {da_event_id} not found in apex_application_page_da "
                f"after create"
            ),
            suggestion="Manual investigation required",
        )

    after, _ = query_metadata_snapshot(profile, app_id)

    export_result = refresh_export(
        sqlcl_conn=profile.sqlcl_name,
        app_id=app_id,
        export_dir=profile.auto_export_dir,
    )

    return {
        "dry_run": False,
        "app_id": app_id,
        "page_id": page_id,
        "da_event_id": da_event_id,
        "da_action_id": da_action_id,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
