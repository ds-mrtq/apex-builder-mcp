"""apex_bulk_add_items — atomic multi-item create via single ImportSession.

All N create_page_item calls run inside ONE wwv_flow_imp.import_begin/end
block, so they all succeed or all roll back together.
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


@apex_tool(name="apex_bulk_add_items", category=Category.WRITE_CORE)
def apex_bulk_add_items(
    app_id: int,
    page_id: int,
    region_id: int,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Add multiple items in a single ImportSession (atomic)."""
    if not items:
        raise ApexBuilderError(
            code="BULK_EMPTY",
            message="items list is empty",
            suggestion=(
                "Pass at least one item dict {item_id, name, "
                "display_as?, display_sequence?}"
            ),
        )

    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    body_parts: list[str] = []
    for idx, item in enumerate(items):
        try:
            item_id = item["item_id"]
            name = item["name"]
        except KeyError as e:
            raise ApexBuilderError(
                code="BULK_ITEM_MISSING_FIELD",
                message=f"items[{idx}] missing required field: {e}",
                suggestion="Each item must have item_id and name",
            ) from e
        display_as = item.get("display_as", "NATIVE_TEXT_FIELD")
        sequence = item.get("display_sequence", 10)
        body_parts.append(
            f"  wwv_flow_imp_page.create_page_item("
            f"p_id => {item_id}, "
            f"p_flow_id => {app_id}, "
            f"p_flow_step_id => {page_id}, "
            f"p_name => '{name}', "
            f"p_item_sequence => {sequence}, "
            f"p_item_plug_id => {region_id}, "
            f"p_display_as => '{display_as}'"
            f");"
        )
    plsql_body = "\n".join(body_parts) + "\n"
    expected_count = len(items)

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_bulk_add_items",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
            "item_count": expected_count,
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
            message=f"apex_bulk_add_items failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(
        before, after, expected_delta={"items": expected_count}
    )
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"bulk add completed but metadata mismatch: {reason}",
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
        "item_count": expected_count,
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
