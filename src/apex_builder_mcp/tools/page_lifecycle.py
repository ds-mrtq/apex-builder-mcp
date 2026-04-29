"""Page lifecycle write tools: apex_delete_page and apex_update_page.

Both DEV-only. Wrap PL/SQL calls in wwv_flow_imp.import_begin/import_end via
ImportSession. Per Phase 0 discovery (ALL_ARGUMENTS):

  * wwv_flow_imp_page.remove_page(p_flow_id, p_page_id)
  * wwv_flow_imp.update_page(p_id, p_flow_id, p_tab_set, p_name, p_step_title,
                             p_step_sub_title, ...)

Note: UPDATE_PAGE does NOT have p_alias / p_page_template_options /
p_autocomplete_on_off — only the core textual page attributes. We expose
the most common attributes (name, step_title, step_sub_title, page_comment).
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


@apex_tool(name="apex_delete_page", category=Category.WRITE_CORE)
def apex_delete_page(app_id: int, page_id: int) -> dict[str, Any]:
    """Delete a page via wwv_flow_imp_page.remove_page (in import session). DEV-only."""
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    plsql_body = (
        f"  wwv_flow_imp_page.remove_page("
        f"p_flow_id => {app_id}, "
        f"p_page_id => {page_id}"
        f");\n"
    )

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_delete_page",
            is_destructive=True,
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
            message=f"apex_delete_page failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"pages": -1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"page delete completed but metadata mismatch: {reason}",
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


@apex_tool(name="apex_update_page", category=Category.WRITE_CORE)
def apex_update_page(
    app_id: int,
    page_id: int,
    name: str | None = None,
    step_title: str | None = None,
    step_sub_title: str | None = None,
    page_comment: str | None = None,
) -> dict[str, Any]:
    """Update a page via wwv_flow_imp.update_page. DEV-only.

    All fields except app_id/page_id are optional; only provided fields are
    sent to the underlying APEX proc. At least one updatable field is required
    (otherwise UPDATE_NO_FIELDS error).
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    parts: list[str] = [
        f"    p_id => {page_id}",
        f"    p_flow_id => {app_id}",
    ]
    if name is not None:
        parts.append(f"    p_name => '{name}'")
    if step_title is not None:
        parts.append(f"    p_step_title => '{step_title}'")
    if step_sub_title is not None:
        parts.append(f"    p_step_sub_title => '{step_sub_title}'")
    if page_comment is not None:
        parts.append(f"    p_page_comment => '{page_comment}'")

    # Require at least one *updatable* field (i.e. beyond p_id + p_flow_id).
    if len(parts) == 2:
        raise ApexBuilderError(
            code="UPDATE_NO_FIELDS",
            message="apex_update_page requires at least one updatable field",
            suggestion="Pass name, step_title, step_sub_title, or page_comment",
        )

    plsql_body = "  wwv_flow_imp.update_page(\n" + ",\n".join(parts) + "\n  );\n"

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_update_page",
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
            message=f"apex_update_page failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"page update completed but metadata mismatch: {reason}",
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
