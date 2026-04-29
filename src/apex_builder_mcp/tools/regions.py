"""apex_add_region — DEV-only write tool wrapping wwv_flow_imp_page.create_page_plug."""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.apex_api.import_session import ImportSession
from apex_builder_mcp.audit.auto_export import refresh_export
from apex_builder_mcp.audit.post_write_verify import (
    verify_post_fail,
    verify_post_success,
)
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.guard.policy import PolicyContext, enforce_policy
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.tools._write_helpers import (
    query_metadata_snapshot,
    query_workspace_id,
)


@apex_tool(name="apex_add_region", category=Category.WRITE_CORE)
def apex_add_region(
    app_id: int,
    page_id: int,
    region_id: int,
    name: str,
    template_id: int = 0,
    display_sequence: int = 10,
    source_type: str = "NATIVE_HTML",
    query_options: str = "DERIVED_REPORT_COLUMNS",
) -> dict[str, Any]:
    """Add a region to a page via wwv_flow_imp_page.create_page_plug. DEV-only."""
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    plsql_body = f"""  wwv_flow_imp_page.create_page_plug(
    p_id => {region_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_plug_name => '{name}',
    p_plug_template => {template_id},
    p_plug_display_sequence => {display_sequence},
    p_plug_source_type => '{source_type}',
    p_plug_query_options => '{query_options}'
  );
"""

    decision = enforce_policy(
        PolicyContext(profile=profile, tool_name="apex_add_region", is_destructive=False)
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
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
            message=f"apex_add_region failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"regions": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"region write completed but metadata mismatch: {reason}",
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
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
