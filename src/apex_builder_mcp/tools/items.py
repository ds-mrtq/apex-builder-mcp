"""apex_add_item — DEV-only write tool wrapping wwv_flow_imp_page.create_page_item."""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.apex_api.import_session import ImportSession
from apex_builder_mcp.audit.auto_export import refresh_export
from apex_builder_mcp.audit.post_write_verify import (
    MetadataSnapshot,
    verify_post_fail,
    verify_post_success,
)
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.guard.policy import PolicyContext, enforce_policy
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError


def _get_pool() -> Any:
    from apex_builder_mcp.tools.connection import _get_or_create_pool
    return _get_or_create_pool()


def _query_workspace_id(conn: Any, workspace: str) -> int:
    cur = conn.cursor()
    cur.execute(
        "select workspace_id from apex_workspaces where upper(workspace) = :w",
        w=workspace.upper(),
    )
    row = cur.fetchone()
    if row is None:
        raise ApexBuilderError(
            code="WORKSPACE_NOT_FOUND",
            message=f"workspace {workspace!r} not found",
            suggestion="Verify workspace name",
        )
    return int(row[0])


def _snapshot(conn: Any, app_id: int) -> tuple[MetadataSnapshot, str]:
    cur = conn.cursor()
    cur.execute(
        """
        select pages,
               (select count(*) from apex_application_page_regions where application_id = :a),
               (select count(*) from apex_application_page_items where application_id = :a),
               alias
          from apex_applications where application_id = :a
        """,
        a=app_id,
    )
    row = cur.fetchone()
    if row is None:
        raise ApexBuilderError(
            code="APP_NOT_FOUND",
            message=f"application_id={app_id} not found",
            suggestion="Verify with apex_list_apps",
        )
    return (
        MetadataSnapshot(pages=int(row[0]), regions=int(row[1]), items=int(row[2])),
        str(row[3]) if row[3] else "",
    )


@apex_tool(name="apex_add_item", category=Category.WRITE_CORE)
def apex_add_item(
    app_id: int,
    page_id: int,
    item_id: int,
    region_id: int,
    name: str,
    display_as: str = "NATIVE_TEXT_FIELD",
    display_sequence: int = 10,
) -> dict[str, Any]:
    """Add an item to a region via wwv_flow_imp_page.create_page_item. DEV-only."""
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    plsql_body = f"""  wwv_flow_imp_page.create_page_item(
    p_id => {item_id},
    p_name => '{name}',
    p_item_sequence => {display_sequence},
    p_item_plug_id => {region_id},
    p_display_as => '{display_as}'
  );
"""

    decision = enforce_policy(
        PolicyContext(profile=profile, tool_name="apex_add_item", is_destructive=False)
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

    pool = _get_pool()
    with pool.acquire() as conn:
        ws_id = _query_workspace_id(conn, profile.workspace)
        before, alias = _snapshot(conn, app_id)

    sess = ImportSession(
        sqlcl_conn=profile.sqlcl_name,
        workspace_id=ws_id,
        application_id=app_id,
        schema=profile.workspace,
    )
    try:
        sess.execute(plsql_body)
    except Exception as e:
        with pool.acquire() as conn:
            after_fail, _ = _snapshot(conn, app_id)
        verify_post_fail(before, after_fail)
        raise ApexBuilderError(
            code="WRITE_EXEC_FAIL",
            message=f"apex_add_item failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    with pool.acquire() as conn:
        after, _ = _snapshot(conn, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"items": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"item write completed but metadata mismatch: {reason}",
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
        "region_id": region_id,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
