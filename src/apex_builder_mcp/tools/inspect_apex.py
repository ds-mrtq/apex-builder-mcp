"""Read-only APEX inspection tools (auto-loaded after apex_connect)."""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool


def _get_pool() -> Any:
    from apex_builder_mcp.tools.connection import _get_or_create_pool
    return _get_or_create_pool()


@apex_tool(name="apex_list_apps", category=Category.READ_APEX)
def apex_list_apps(workspace: str | None = None) -> dict[str, Any]:
    """List APEX applications (optionally filtered by workspace)."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        if workspace:
            cur.execute(
                "select application_id, application_name, alias, pages "
                "from apex_applications where workspace = :ws "
                "order by application_id",
                ws=workspace.upper(),
            )
        else:
            cur.execute(
                "select application_id, application_name, alias, pages "
                "from apex_applications order by application_id"
            )
        apps = [
            {
                "application_id": r[0],
                "application_name": r[1],
                "alias": r[2],
                "pages": r[3],
            }
            for r in cur.fetchall()
        ]
    return {"apps": apps, "count": len(apps)}


@apex_tool(name="apex_describe_app", category=Category.READ_APEX)
def apex_describe_app(app_id: int) -> dict[str, Any]:
    """Describe an APEX app: pages, alias, owner, auth, etc."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select application_name, alias, pages, owner,
                   authentication_scheme, page_template
              from apex_applications where application_id = :a
            """,
            a=app_id,
        )
        row = cur.fetchone()
        if row is None:
            return {"application_id": app_id, "found": False}
        cur.execute(
            "select count(*) from apex_application_lovs where application_id = :a",
            a=app_id,
        )
        lov_row = cur.fetchone()
        lov_count = lov_row[0] if lov_row else 0
    return {
        "application_id": app_id,
        "application_name": row[0],
        "alias": row[1],
        "pages": row[2],
        "owner": row[3],
        "authentication_scheme": row[4],
        "page_template": row[5],
        "lov_count": lov_count,
        "found": True,
    }


@apex_tool(name="apex_list_pages", category=Category.READ_APEX)
def apex_list_pages(app_id: int) -> dict[str, Any]:
    """List pages of an app."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select page_id, page_name from apex_application_pages "
            "where application_id = :a order by page_id",
            a=app_id,
        )
        pages = [{"page_id": r[0], "page_name": r[1]} for r in cur.fetchall()]
    return {"app_id": app_id, "pages": pages, "count": len(pages)}


@apex_tool(name="apex_describe_page", category=Category.READ_APEX)
def apex_describe_page(app_id: int, page_id: int) -> dict[str, Any]:
    """Describe a page with its regions, items, buttons, processes."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select page_name, page_alias, page_mode, requires_authentication
              from apex_application_pages
             where application_id = :a and page_id = :p
            """,
            a=app_id, p=page_id,
        )
        row = cur.fetchone()
        if row is None:
            return {"app_id": app_id, "page_id": page_id, "found": False}
        cur.execute(
            "select region_id, region_name, display_position, display_sequence "
            "from apex_application_page_regions "
            "where application_id = :a and page_id = :p order by display_sequence",
            a=app_id, p=page_id,
        )
        regions = [
            {"region_id": r[0], "name": r[1], "position": r[2], "sequence": r[3]}
            for r in cur.fetchall()
        ]
        cur.execute(
            "select item_id, item_name, display_as, item_plug_id "
            "from apex_application_page_items "
            "where application_id = :a and page_id = :p order by item_sequence",
            a=app_id, p=page_id,
        )
        items = [
            {"item_id": r[0], "name": r[1], "display_as": r[2], "region_id": r[3]}
            for r in cur.fetchall()
        ]
        cur.execute(
            "select button_id, button_name, button_plug_id, button_action "
            "from apex_application_page_buttons "
            "where application_id = :a and page_id = :p",
            a=app_id, p=page_id,
        )
        buttons = [
            {"button_id": r[0], "name": r[1], "region_id": r[2], "action": r[3]}
            for r in cur.fetchall()
        ]
        cur.execute(
            "select process_id, process_name, process_type, process_sequence "
            "from apex_application_page_proc "
            "where application_id = :a and page_id = :p order by process_sequence",
            a=app_id, p=page_id,
        )
        processes = [
            {"process_id": r[0], "name": r[1], "type": r[2], "sequence": r[3]}
            for r in cur.fetchall()
        ]
    return {
        "app_id": app_id,
        "page_id": page_id,
        "page_name": row[0],
        "page_alias": row[1],
        "page_mode": row[2],
        "requires_authentication": row[3],
        "regions": regions,
        "items": items,
        "buttons": buttons,
        "processes": processes,
        "found": True,
    }


@apex_tool(name="apex_describe_acl", category=Category.READ_APEX)
def apex_describe_acl(app_id: int) -> dict[str, Any]:
    """Read-only snapshot of ACL assignments for an app."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select user_name, role_static_id from apex_appl_acl_user_roles "
            "where application_id = :a order by upper(user_name), role_static_id",
            a=app_id,
        )
        rows = [
            {"user_name": r[0], "role_static_id": r[1]}
            for r in cur.fetchall()
        ]
    return {"app_id": app_id, "assignments": rows, "count": len(rows)}
