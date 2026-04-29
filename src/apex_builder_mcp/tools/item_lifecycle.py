"""Item lifecycle write tools: apex_delete_item and apex_update_item.

Per Phase 0 discovery (ALL_ARGUMENTS):
  * wwv_flow_app_builder_api.delete_page_item(p_page_id, p_item_id)
  * wwv_flow_imp.update_page_item(p_flow_id, p_page_id, p_item_id,
                                  p_new_sequence, p_display_as,
                                  p_new_name, p_new_label,
                                  p_new_begin_new_line, p_new_begin_new_field,
                                  p_attribute_01..15)

We expose the most common updatable fields (label, name, display_as,
sequence) on apex_update_item.
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


@apex_tool(name="apex_delete_item", category=Category.WRITE_CORE)
def apex_delete_item(
    app_id: int,
    page_id: int,
    item_id: int,
) -> dict[str, Any]:
    """Delete an item via wwv_flow_app_builder_api.delete_page_item. DEV-only."""
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    plsql_body = (
        f"  wwv_flow_app_builder_api.delete_page_item("
        f"p_page_id => {page_id}, "
        f"p_item_id => {item_id}"
        f");\n"
    )

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_delete_item",
            is_destructive=True,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "item_id": item_id,
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
            message=f"apex_delete_item failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"items": -1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"item delete completed but metadata mismatch: {reason}",
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
        "item_id": item_id,
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


@apex_tool(name="apex_update_item", category=Category.WRITE_CORE)
def apex_update_item(
    app_id: int,
    page_id: int,
    item_id: int,
    label: str | None = None,
    name: str | None = None,
    display_as: str | None = None,
    display_sequence: int | None = None,
) -> dict[str, Any]:
    """Update a page item via wwv_flow_imp.update_page_item. DEV-only.

    Only provided fields are sent to APEX; at least one updatable field
    is required (otherwise UPDATE_NO_FIELDS).
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
        f"    p_flow_id => {app_id}",
        f"    p_page_id => {page_id}",
        f"    p_item_id => {item_id}",
    ]
    if label is not None:
        parts.append(f"    p_new_label => '{label}'")
    if name is not None:
        parts.append(f"    p_new_name => '{name}'")
    if display_as is not None:
        parts.append(f"    p_display_as => '{display_as}'")
    if display_sequence is not None:
        parts.append(f"    p_new_sequence => {display_sequence}")

    # Require at least one *updatable* field (i.e. beyond the 3 keys).
    if len(parts) == 3:
        raise ApexBuilderError(
            code="UPDATE_NO_FIELDS",
            message="apex_update_item requires at least one updatable field",
            suggestion="Pass label, name, display_as, or display_sequence",
        )

    plsql_body = "  wwv_flow_imp.update_page_item(\n" + ",\n".join(parts) + "\n  );\n"

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_update_item",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "item_id": item_id,
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
            message=f"apex_update_item failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"item update completed but metadata mismatch: {reason}",
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
        "item_id": item_id,
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
