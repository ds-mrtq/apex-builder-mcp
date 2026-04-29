"""Region lifecycle write tools: apex_delete_region.

apex_update_region is DEFERRED — APEX has no public UPDATE_REGION procedure
in WWV_FLOW_APP_BUILDER_API. Updates are normally expressed via re-importing
a full page snapshot (out of scope for Bundle 2).

Per Phase 0 discovery (ALL_ARGUMENTS):
  * wwv_flow_app_builder_api.delete_region(p_page_id, p_region_id)

NOTE: app_builder_api procs do NOT need ImportSession context. They are
public APEX management procs that work outside an import session, but they
require the apex_240200.* schema prefix.
"""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.audit.auto_export import refresh_export
from apex_builder_mcp.audit.post_write_verify import (
    verify_post_fail,
    verify_post_success,
)
from apex_builder_mcp.connection.sqlcl_subprocess import has_db_error, run_sqlcl
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.guard.policy import PolicyContext, enforce_policy
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.tools._write_helpers import query_metadata_snapshot


@apex_tool(name="apex_delete_region", category=Category.WRITE_CORE)
def apex_delete_region(
    app_id: int,
    page_id: int,
    region_id: int,
) -> dict[str, Any]:
    """Delete a region via wwv_flow_app_builder_api.delete_region. DEV-only.

    NOTE: app_builder_api procs do NOT need ImportSession context. Called
    directly with apex_240200.* schema prefix.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    sql = (
        f"set echo off feedback on define off verify off\n"
        f"whenever sqlerror exit sql.sqlcode rollback\n"
        f"begin\n"
        f"  apex_util.set_workspace(p_workspace => '{profile.workspace}');\n"
        f"  apex_240200.wwv_flow_app_builder_api.set_application_id("
        f"p_application_id => {app_id});\n"
        f"  apex_240200.wwv_flow_app_builder_api.delete_region(\n"
        f"    p_page_id => {page_id},\n"
        f"    p_region_id => {region_id}\n"
        f"  );\n"
        f"  commit;\n"
        f"end;\n"
        f"/\n"
        f"exit\n"
    )

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_delete_region",
            is_destructive=True,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
            "sql_preview": sql,
        }

    before, alias_resolved = query_metadata_snapshot(profile, app_id)

    result = run_sqlcl(profile.sqlcl_name, sql, timeout=60)
    if result.rc != 0 or has_db_error(result.stdout):
        after_fail, _ = query_metadata_snapshot(profile, app_id)
        verify_post_fail(before, after_fail)
        raise ApexBuilderError(
            code="WRITE_EXEC_FAIL",
            message=f"apex_delete_region failed: {result.cleaned}",
            suggestion="Verify region_id exists; check app_builder_api signature",
        )

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"regions": -1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"region delete completed but metadata mismatch: {reason}",
            suggestion="Manual investigation required",
        )

    export_result = refresh_export(
        sqlcl_conn=profile.sqlcl_name,
        app_id=app_id,
        export_dir=profile.auto_export_dir,
    )

    return {
        "dry_run": False,
        "app_id": app_id,
        "page_id": page_id,
        "region_id": region_id,
        "alias": alias_resolved,
        "before": {
            "pages": before.pages,
            "regions": before.regions,
            "items": before.items,
        },
        "after": {
            "pages": after.pages,
            "regions": after.regions,
            "items": after.items,
        },
        "auto_export": export_result,
    }
