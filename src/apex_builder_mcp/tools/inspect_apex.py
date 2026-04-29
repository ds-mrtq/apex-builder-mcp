"""Read-only APEX inspection tools (auto-loaded after apex_connect).

All tools branch on ``profile.auth_mode`` via the shared helpers in
``tools/_read_helpers.py``: under ``auth_mode=sqlcl`` (default) reads run
through the SQLcl subprocess; under ``auth_mode=password`` they use the
oracledb pool. External signatures and return shapes are unchanged.
"""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools._read_helpers import (
    query_describe_acl,
    query_describe_app,
    query_describe_page,
    query_list_apps,
    query_list_dynamic_actions,
    query_list_items,
    query_list_pages,
    query_list_processes,
    query_list_regions,
    query_page_details,
    query_workspace_users,
)


def _require_profile() -> Profile:
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    return state.profile


@apex_tool(name="apex_list_apps", category=Category.READ_APEX)
def apex_list_apps(workspace: str | None = None) -> dict[str, Any]:
    """List APEX applications (optionally filtered by workspace)."""
    profile = _require_profile()
    apps = query_list_apps(profile, workspace)
    return {"apps": apps, "count": len(apps)}


@apex_tool(name="apex_describe_app", category=Category.READ_APEX)
def apex_describe_app(app_id: int) -> dict[str, Any]:
    """Describe an APEX app: pages, alias, owner, auth, etc."""
    profile = _require_profile()
    app = query_describe_app(profile, app_id)
    if app is None:
        return {"application_id": app_id, "found": False}
    return {
        "application_id": app_id,
        "application_name": app["application_name"],
        "alias": app["alias"],
        "pages": app["pages"],
        "owner": app["owner"],
        "authentication_scheme": app["authentication_scheme"],
        "page_template": app["page_template"],
        "lov_count": app["lov_count"],
        "found": True,
    }


@apex_tool(name="apex_list_pages", category=Category.READ_APEX)
def apex_list_pages(app_id: int) -> dict[str, Any]:
    """List pages of an app."""
    profile = _require_profile()
    pages = query_list_pages(profile, app_id)
    return {"app_id": app_id, "pages": pages, "count": len(pages)}


@apex_tool(name="apex_describe_page", category=Category.READ_APEX)
def apex_describe_page(app_id: int, page_id: int) -> dict[str, Any]:
    """Describe a page with its regions, items, buttons, processes."""
    profile = _require_profile()
    page = query_describe_page(profile, app_id, page_id)
    if page is None:
        return {"app_id": app_id, "page_id": page_id, "found": False}
    return {
        "app_id": app_id,
        "page_id": page_id,
        "page_name": page["page_name"],
        "page_alias": page["page_alias"],
        "page_mode": page["page_mode"],
        "requires_authentication": page["requires_authentication"],
        "regions": page["regions"],
        "items": page["items"],
        "buttons": page["buttons"],
        "processes": page["processes"],
        "found": True,
    }


@apex_tool(name="apex_describe_acl", category=Category.READ_APEX)
def apex_describe_acl(app_id: int) -> dict[str, Any]:
    """Read-only snapshot of ACL assignments for an app."""
    profile = _require_profile()
    rows = query_describe_acl(profile, app_id)
    return {"app_id": app_id, "assignments": rows, "count": len(rows)}


@apex_tool(name="apex_get_page_details", category=Category.READ_APEX)
def apex_get_page_details(app_id: int, page_id: int) -> dict[str, Any]:
    """Full page metadata from apex_application_pages."""
    profile = _require_profile()
    details = query_page_details(profile, app_id, page_id)
    if details is None:
        return {"app_id": app_id, "page_id": page_id, "found": False}
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
    profile = _require_profile()
    rows = query_list_regions(profile, app_id, page_id)
    return {"app_id": app_id, "page_id": page_id, "regions": rows, "count": len(rows)}


@apex_tool(name="apex_list_items", category=Category.READ_APEX)
def apex_list_items(app_id: int, page_id: int) -> dict[str, Any]:
    """List items of a page with display attributes."""
    profile = _require_profile()
    rows = query_list_items(profile, app_id, page_id)
    return {"app_id": app_id, "page_id": page_id, "items": rows, "count": len(rows)}


@apex_tool(name="apex_list_processes", category=Category.READ_APEX)
def apex_list_processes(app_id: int, page_id: int) -> dict[str, Any]:
    """List page processes with type, point, sequence, and PL/SQL body."""
    profile = _require_profile()
    rows = query_list_processes(profile, app_id, page_id)
    return {"app_id": app_id, "page_id": page_id, "processes": rows, "count": len(rows)}


@apex_tool(name="apex_list_workspace_users", category=Category.READ_APEX)
def apex_list_workspace_users(workspace: str | None = None) -> dict[str, Any]:
    """List APEX workspace users (optionally filtered by workspace).

    Reads from `apex_workspace_apex_users`. Returns user_name, is_admin
    (workspace_admin), is_developer (i.e. is_application_developer),
    account_locked, last_login (date_last_login), workspace_name, and email.

    Branches on profile.auth_mode: SQLcl subprocess vs oracledb pool.
    """
    profile = _require_profile()
    users = query_workspace_users(profile, workspace)
    return {
        "workspace": workspace.upper() if workspace else None,
        "users": users,
        "count": len(users),
    }


@apex_tool(name="apex_list_dynamic_actions", category=Category.READ_APEX)
def apex_list_dynamic_actions(app_id: int, page_id: int) -> dict[str, Any]:
    """List dynamic action events on a page (event name, when-element, type)."""
    profile = _require_profile()
    events = query_list_dynamic_actions(profile, app_id, page_id)
    return {
        "app_id": app_id,
        "page_id": page_id,
        "dynamic_actions": events,
        "count": len(events),
    }
