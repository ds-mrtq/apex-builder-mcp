"""Read-only APEX inspection tools (auto-loaded after apex_connect)."""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.tools._read_helpers import query_workspace_users


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


@apex_tool(name="apex_get_page_details", category=Category.READ_APEX)
def apex_get_page_details(app_id: int, page_id: int) -> dict[str, Any]:
    """Full page metadata from apex_application_pages."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select page_name, page_alias, page_mode, requires_authentication,
                   page_function, page_template, primary_navigation_list,
                   security_authorization_scheme, primary_user_interface,
                   inline_css, javascript_code_onload, page_template_options
              from apex_application_pages
             where application_id = :a and page_id = :p
            """,
            a=app_id, p=page_id,
        )
        row = cur.fetchone()
        if row is None:
            return {"app_id": app_id, "page_id": page_id, "found": False}
        cols = [d[0] for d in cur.description]
    details = dict(zip(cols, row, strict=False))
    return {"app_id": app_id, "page_id": page_id, "found": True, "details": details}


@apex_tool(name="apex_describe_page_human", category=Category.READ_APEX)
def apex_describe_page_human(app_id: int, page_id: int) -> dict[str, Any]:
    """Human-readable Markdown summary of a page (for LLM context)."""
    page_data = apex_describe_page(app_id, page_id)
    if not page_data.get("found", True) or page_data.get("page_name") is None:
        return {"app_id": app_id, "page_id": page_id, "found": False, "summary": ""}

    lines = [
        f"# Page {page_id}: {page_data['page_name']}",
        f"- Alias: {page_data.get('page_alias') or '(none)'}",
        f"- Mode: {page_data.get('page_mode')}",
        f"- Requires authentication: {page_data.get('requires_authentication')}",
        "",
        f"## Regions ({len(page_data.get('regions', []))})",
    ]
    for r in page_data.get("regions", []):
        lines.append(
            f"- [{r['region_id']}] {r['name']} "
            f"(position={r['position']}, seq={r['sequence']})"
        )
    lines.append("")
    lines.append(f"## Items ({len(page_data.get('items', []))})")
    for it in page_data.get("items", []):
        lines.append(
            f"- [{it['item_id']}] {it['name']} ({it['display_as']}) "
            f"in region {it['region_id']}"
        )
    lines.append("")
    lines.append(f"## Buttons ({len(page_data.get('buttons', []))})")
    for b in page_data.get("buttons", []):
        lines.append(f"- [{b['button_id']}] {b['name']} action={b['action']}")
    lines.append("")
    lines.append(f"## Processes ({len(page_data.get('processes', []))})")
    for pr in page_data.get("processes", []):
        lines.append(f"- [{pr['process_id']}] {pr['name']} type={pr['type']}")

    return {
        "app_id": app_id,
        "page_id": page_id,
        "found": True,
        "summary": "\n".join(lines),
    }


@apex_tool(name="apex_list_regions", category=Category.READ_APEX)
def apex_list_regions(app_id: int, page_id: int) -> dict[str, Any]:
    """List regions of a page with display sequence + template info."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select region_id, region_name, display_position, display_sequence,
                   region_template, source, source_type
              from apex_application_page_regions
             where application_id = :a and page_id = :p
             order by display_sequence
            """,
            a=app_id, p=page_id,
        )
        rows = [
            {
                "region_id": r[0],
                "region_name": r[1],
                "position": r[2],
                "sequence": r[3],
                "template": r[4],
                "source": r[5],
                "source_type": r[6],
            }
            for r in cur.fetchall()
        ]
    return {"app_id": app_id, "page_id": page_id, "regions": rows, "count": len(rows)}


@apex_tool(name="apex_list_items", category=Category.READ_APEX)
def apex_list_items(app_id: int, page_id: int) -> dict[str, Any]:
    """List items of a page with display attributes."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select item_id, item_name, display_as, item_plug_id,
                   item_sequence, label, prompt
              from apex_application_page_items
             where application_id = :a and page_id = :p
             order by item_sequence
            """,
            a=app_id, p=page_id,
        )
        rows = [
            {
                "item_id": r[0],
                "name": r[1],
                "display_as": r[2],
                "region_id": r[3],
                "sequence": r[4],
                "label": r[5],
                "prompt": r[6],
            }
            for r in cur.fetchall()
        ]
    return {"app_id": app_id, "page_id": page_id, "items": rows, "count": len(rows)}


@apex_tool(name="apex_list_processes", category=Category.READ_APEX)
def apex_list_processes(app_id: int, page_id: int) -> dict[str, Any]:
    """List page processes with type, point, sequence, and PL/SQL body."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select process_id, process_name, process_type, process_sequence, "
            "process_point, process_sql_clob "
            "from apex_application_page_proc "
            "where application_id = :a and page_id = :p order by process_sequence",
            a=app_id, p=page_id,
        )
        rows = [
            {
                "process_id": r[0],
                "name": r[1],
                "type": r[2],
                "sequence": r[3],
                "point": r[4],
                "code": str(r[5]) if r[5] else None,
            }
            for r in cur.fetchall()
        ]
    return {"app_id": app_id, "page_id": page_id, "processes": rows, "count": len(rows)}


@apex_tool(name="apex_list_workspace_users", category=Category.READ_APEX)
def apex_list_workspace_users(workspace: str | None = None) -> dict[str, Any]:
    """List APEX workspace users (optionally filtered by workspace).

    Reads from `apex_workspace_apex_users`. Returns user_name, is_admin
    (workspace_admin), is_developer (i.e. is_application_developer),
    account_locked, last_login (date_last_login), workspace_name, and email.

    Branches on profile.auth_mode: SQLcl subprocess vs oracledb pool.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    users = query_workspace_users(state.profile, workspace)
    return {
        "workspace": workspace.upper() if workspace else None,
        "users": users,
        "count": len(users),
    }


@apex_tool(name="apex_list_dynamic_actions", category=Category.READ_APEX)
def apex_list_dynamic_actions(app_id: int, page_id: int) -> dict[str, Any]:
    """List dynamic action events on a page (event name, when-element, type)."""
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select dynamic_action_id, dynamic_action_name, when_event_name, "
            "when_element_type, when_element "
            "from apex_application_page_da "
            "where application_id = :a and page_id = :p order by event_sequence",
            a=app_id, p=page_id,
        )
        events = [
            {
                "da_id": r[0],
                "name": r[1],
                "event": r[2],
                "element_type": r[3],
                "element": r[4],
            }
            for r in cur.fetchall()
        ]
    return {
        "app_id": app_id,
        "page_id": page_id,
        "dynamic_actions": events,
        "count": len(events),
    }
