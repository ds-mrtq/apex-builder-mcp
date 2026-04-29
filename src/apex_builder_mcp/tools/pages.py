"""apex_add_page — DEV-only write tool wrapping wwv_flow_imp_page.create_page.

Per Phase 0 finding #1: must wrap in wwv_flow_imp.import_begin/import_end via
ImportSession helper. Per Phase 0 finding #5: minimum page params are
p_id, p_name, p_alias, p_step_title, p_autocomplete_on_off, p_page_template_options.
"""
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


@apex_tool(name="apex_add_page", category=Category.WRITE_CORE)
def apex_add_page(
    app_id: int,
    page_id: int,
    name: str,
    alias: str | None = None,
    page_template_options: str = "#DEFAULT#",
    autocomplete: bool = False,
) -> dict[str, Any]:
    """Add a page to an existing APEX app via wwv_flow_imp_page.create_page.

    DEV environments only. TEST returns dry-run SQL preview. PROD rejects.
    Wraps the call in wwv_flow_imp.import_begin/import_end (Phase 0 finding).
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    alias_value = (alias or name).upper().replace(" ", "_")
    autocomplete_value = "ON" if autocomplete else "OFF"
    plsql_body = f"""  wwv_flow_imp_page.create_page(
    p_id => {page_id},
    p_name => '{name}',
    p_alias => '{alias_value}',
    p_step_title => '{name}',
    p_autocomplete_on_off => '{autocomplete_value}',
    p_page_template_options => '{page_template_options}'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_add_page",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "sql_preview": (
                f"-- import_begin/import_end wrap for app {app_id}\n"
                f"-- body:\n{plsql_body}"
            ),
        }

    ws_id = query_workspace_id(profile, profile.workspace)
    before, alias_resolved = query_metadata_snapshot(profile, app_id)

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
            message=f"apex_add_page failed: {e}",
            suggestion="Check SQL preview via dry_run; verify wwv_flow_imp_page param signature",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"pages": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"page write completed but metadata mismatch: {reason}",
            suggestion="Manual investigation required — page may exist in inconsistent state",
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
        "name": name,
        "alias": alias_resolved,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
