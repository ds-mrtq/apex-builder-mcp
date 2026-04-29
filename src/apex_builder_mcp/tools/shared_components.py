"""Shared-component write/read tools for Plan 2B-5.

Implements 5 tools (4 writes + 1 read).

Implemented:
  * apex_add_lov(app_id, lov_id, name, lov_type='STATIC', static_values=None, sql_query=None)
      Creates an application-level List of Values via
      wwv_flow_imp_shared.create_list_of_values + (for STATIC) one
      create_static_lov_data row per (display, return) pair.
      ALL_ARGUMENTS: CREATE_LIST_OF_VALUES (39 params) and
      CREATE_STATIC_LOV_DATA (15 params) — all defaulted.

  * apex_list_lovs(app_id)
      Read-only query: SELECT lov_id, list_of_values_name, lov_type
      FROM apex_application_lovs WHERE application_id = :a.

  * apex_add_auth_scheme(app_id, auth_id, name, scheme_type='CUSTOM',
                         plsql_code='return true;')
      Creates an authentication scheme via
      wwv_flow_imp_shared.create_authentication.
      ALL_ARGUMENTS: 42 params, only p_name + p_scheme_type required.
      For scheme_type='CUSTOM' we pass p_plsql_code as the auth function body.

  * apex_add_nav_item(app_id, list_item_id, list_id, name, target_url, sequence=10)
      Adds an entry to an existing navigation list via
      wwv_flow_imp_shared.create_list_item.
      Caller must supply existing list_id (typically the app's "Desktop
      Navigation Menu" or similar). ALL_ARGUMENTS: 44 params, all defaulted.

  * apex_add_app_item(app_id, item_id, name, scope='APPLICATION')
      Creates an application-level item (global session-state variable) via
      wwv_flow_imp_shared.create_flow_item.
      ALL_ARGUMENTS: 16 params, all defaulted.
      Note: APEX terminology — "application item" = "flow item" at the
      internal proc level. The p_scope param ('APPLICATION' or 'SESSION')
      controls lifetime.

NOTE on shared-component import session: wwv_flow_imp_shared.* procs DO
require the import_begin/import_end wrapper because they reference
g_security_group_id (set by import_begin). Empirically verified with the
authentication scheme proc; the same is true for LOV/list/flow-item procs.
We use ImportSession for all writes here.
"""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.apex_api.import_session import ImportSession
from apex_builder_mcp.audit.auto_export import refresh_export
from apex_builder_mcp.audit.post_write_verify import verify_post_fail
from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.guard.policy import PolicyContext, enforce_policy
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools._read_helpers import query_lovs
from apex_builder_mcp.tools._write_helpers import (
    query_metadata_snapshot,
    query_workspace_id,
)

# ---------------------------------------------------------------------------
# Verification helpers (shared components are NOT in MetadataSnapshot,
# so we query domain views directly)
# ---------------------------------------------------------------------------


def _verify_lov_exists(profile: Profile, app_id: int, lov_id: int) -> bool:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select count(*) from apex_application_lovs "
        f"where application_id = {app_id} and lov_id = {lov_id};\nexit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s) == 1
    return False


def _verify_auth_exists(profile: Profile, app_id: int, auth_id: int) -> bool:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select count(*) from apex_application_auth "
        f"where application_id = {app_id} and authentication_scheme_id = {auth_id};\n"
        "exit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s) == 1
    return False


def _verify_list_item_exists(
    profile: Profile, app_id: int, list_id: int, list_item_id: int
) -> bool:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select count(*) from apex_application_list_entries "
        f"where application_id = {app_id} and list_id = {list_id} "
        f"and list_entry_id = {list_item_id};\n"
        "exit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s) == 1
    return False


def _verify_app_item_exists(profile: Profile, app_id: int, item_id: int) -> bool:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select count(*) from apex_application_items "
        f"where application_id = {app_id} and application_item_id = {item_id};\n"
        "exit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s) == 1
    return False


# ---------------------------------------------------------------------------
# Implemented: apex_add_lov
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_lov", category=Category.WRITE_CORE)
def apex_add_lov(
    app_id: int,
    lov_id: int,
    name: str,
    lov_type: str = "STATIC",
    static_values: list[dict[str, str]] | None = None,
    sql_query: str | None = None,
) -> dict[str, Any]:
    """Add an application-level LOV via wwv_flow_imp_shared.create_list_of_values.

    DEV-only. TEST returns dry-run preview. PROD rejects.

    For lov_type='STATIC':
      static_values is a list of {"display": str, "return": str} dicts.
      Each generates one wwv_flow_imp_shared.create_static_lov_data row.

    For lov_type='DYNAMIC':
      sql_query becomes p_lov_query.

    Verification: queries apex_application_lovs by lov_id.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    lov_type_norm = lov_type.upper()
    if lov_type_norm not in ("STATIC", "DYNAMIC"):
        raise ApexBuilderError(
            code="INVALID_PARAM",
            message=f"lov_type must be STATIC or DYNAMIC, got {lov_type!r}",
            suggestion="Use lov_type='STATIC' or 'DYNAMIC'",
        )
    if lov_type_norm == "DYNAMIC" and not sql_query:
        raise ApexBuilderError(
            code="INVALID_PARAM",
            message="sql_query required when lov_type='DYNAMIC'",
            suggestion="Pass sql_query='select d, r from t'",
        )

    name_esc = name.replace("'", "''")
    sql_esc = (sql_query or "").replace("'", "''")
    source_type = "LEGACY_SQL" if lov_type_norm == "DYNAMIC" else "STATIC"

    body_lines = [
        "  wwv_flow_imp_shared.create_list_of_values(",
        f"    p_id => {lov_id},",
        f"    p_flow_id => {app_id},",
        f"    p_lov_name => '{name_esc}',",
        f"    p_source_type => '{source_type}',",
    ]
    if lov_type_norm == "DYNAMIC":
        body_lines.append(f"    p_lov_query => '{sql_esc}'")
    else:
        # close create_list_of_values call without trailing comma
        body_lines[-1] = body_lines[-1].rstrip(",")
    body_lines.append("  );")

    if lov_type_norm == "STATIC" and static_values:
        for idx, entry in enumerate(static_values, start=1):
            disp = (entry.get("display", "") or "").replace("'", "''")
            ret = (entry.get("return", "") or "").replace("'", "''")
            row_id = lov_id + idx  # derived id per static row
            body_lines.append(
                "  wwv_flow_imp_shared.create_static_lov_data("
                f"p_id => {row_id}, p_lov_id => {lov_id}, "
                f"p_lov_disp_sequence => {idx * 10}, "
                f"p_lov_disp_value => '{disp}', "
                f"p_lov_return_value => '{ret}');"
            )

    plsql_body = "\n".join(body_lines) + "\n"

    decision = enforce_policy(
        PolicyContext(profile=profile, tool_name="apex_add_lov", is_destructive=False)
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "lov_id": lov_id,
            "name": name,
            "lov_type": lov_type_norm,
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
            message=f"apex_add_lov failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    if not _verify_lov_exists(profile, app_id, lov_id):
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"LOV {lov_id} not found in apex_application_lovs after create",
            suggestion="Manual investigation required",
        )

    after, _ = query_metadata_snapshot(profile, app_id)

    export_result = refresh_export(
        sqlcl_conn=profile.sqlcl_name,
        app_id=app_id,
        export_dir=profile.auto_export_dir,
    )

    return {
        "dry_run": False,
        "app_id": app_id,
        "lov_id": lov_id,
        "name": name,
        "lov_type": lov_type_norm,
        "alias": alias,
        "static_value_count": len(static_values) if static_values else 0,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }


# ---------------------------------------------------------------------------
# Implemented: apex_list_lovs (read)
# ---------------------------------------------------------------------------


@apex_tool(name="apex_list_lovs", category=Category.READ_APEX)
def apex_list_lovs(app_id: int) -> dict[str, Any]:
    """List LOVs in an APEX application (read-only).

    Branches on profile.auth_mode: SQLcl subprocess vs oracledb pool.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    lovs = query_lovs(state.profile, app_id)
    return {"app_id": app_id, "lovs": lovs, "count": len(lovs)}


# ---------------------------------------------------------------------------
# Implemented: apex_add_auth_scheme
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_auth_scheme", category=Category.WRITE_CORE)
def apex_add_auth_scheme(
    app_id: int,
    auth_id: int,
    name: str,
    scheme_type: str = "NATIVE_CUSTOM",
    plsql_code: str = "return true;",
) -> dict[str, Any]:
    """Add an authentication scheme via wwv_flow_imp_shared.create_authentication.

    DEV-only. TEST returns dry-run preview. PROD rejects.

    Valid scheme_type codes (APEX 24.2):
      * NATIVE_CUSTOM       — custom function-based (uses p_plsql_code)
      * NATIVE_APEX_ACCOUNT — Oracle APEX accounts
      * NATIVE_DB_ACCOUNT   — DB schema authentication
      * NATIVE_LDAP         — LDAP
      * NATIVE_OPEN_DOOR    — no auth (Open Door / dev only)
    Display labels in apex_application_auth (e.g. "Oracle APEX Accounts")
    are derived from these codes; the create_authentication proc requires
    the NATIVE_* codes.

    For scheme_type='NATIVE_CUSTOM' the plsql_code becomes p_plsql_code (the
    auth function body that returns BOOLEAN).

    Verification: queries apex_application_auth by authentication_scheme_id.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    name_esc = name.replace("'", "''")
    type_esc = scheme_type.replace("'", "''")
    code_esc = plsql_code.replace("'", "''")

    plsql_body = f"""  wwv_flow_imp_shared.create_authentication(
    p_id => {auth_id},
    p_flow_id => {app_id},
    p_name => '{name_esc}',
    p_scheme_type => '{type_esc}',
    p_plsql_code => '{code_esc}'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_auth_scheme", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "auth_id": auth_id,
            "name": name,
            "scheme_type": scheme_type,
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
            message=f"apex_add_auth_scheme failed: {e}",
            suggestion="Check SQL preview via dry_run; verify scheme_type valid",
        ) from e

    if not _verify_auth_exists(profile, app_id, auth_id):
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"auth scheme {auth_id} not found in apex_application_auth after "
                f"create"
            ),
            suggestion="Manual investigation required",
        )

    after, _ = query_metadata_snapshot(profile, app_id)

    export_result = refresh_export(
        sqlcl_conn=profile.sqlcl_name,
        app_id=app_id,
        export_dir=profile.auto_export_dir,
    )

    return {
        "dry_run": False,
        "app_id": app_id,
        "auth_id": auth_id,
        "name": name,
        "scheme_type": scheme_type,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }


# ---------------------------------------------------------------------------
# Implemented: apex_add_nav_item
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_nav_item", category=Category.WRITE_CORE)
def apex_add_nav_item(
    app_id: int,
    list_item_id: int,
    list_id: int,
    name: str,
    target_url: str,
    sequence: int = 10,
) -> dict[str, Any]:
    """Add an entry to an existing navigation list (e.g. Desktop Navigation Menu).

    Wraps wwv_flow_imp_shared.create_list_item. Caller supplies existing list_id
    (look it up via apex_application_lists view).

    DEV-only. TEST returns dry-run preview. PROD rejects.

    Verification: queries apex_application_list_entries by list_entry_id.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    name_esc = name.replace("'", "''")
    target_esc = target_url.replace("'", "''")

    plsql_body = f"""  wwv_flow_imp_shared.create_list_item(
    p_id => {list_item_id},
    p_list_id => {list_id},
    p_list_item_display_sequence => {sequence},
    p_list_item_link_text => '{name_esc}',
    p_list_item_link_target => '{target_esc}',
    p_list_item_status => 'PUBLIC'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_nav_item", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "list_id": list_id,
            "list_item_id": list_item_id,
            "name": name,
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
            message=f"apex_add_nav_item failed: {e}",
            suggestion=(
                "Check SQL preview via dry_run; verify list_id exists "
                "(query apex_application_lists)"
            ),
        ) from e

    if not _verify_list_item_exists(profile, app_id, list_id, list_item_id):
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"list entry {list_item_id} not found in "
                f"apex_application_list_entries after create"
            ),
            suggestion="Manual investigation required",
        )

    after, _ = query_metadata_snapshot(profile, app_id)

    export_result = refresh_export(
        sqlcl_conn=profile.sqlcl_name,
        app_id=app_id,
        export_dir=profile.auto_export_dir,
    )

    return {
        "dry_run": False,
        "app_id": app_id,
        "list_id": list_id,
        "list_item_id": list_item_id,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }


# ---------------------------------------------------------------------------
# Implemented: apex_add_app_item
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_app_item", category=Category.WRITE_CORE)
def apex_add_app_item(
    app_id: int,
    item_id: int,
    name: str,
    scope: str = "APPLICATION",
) -> dict[str, Any]:
    """Add an application-level item (global session-state variable).

    APEX terminology: "application item" maps to "flow item" at the internal
    proc level. Wraps wwv_flow_imp_shared.create_flow_item.

    p_scope='APPLICATION' or 'SESSION' controls lifetime.

    Verification: queries apex_application_items by item_id.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    name_esc = name.replace("'", "''").upper()
    scope_norm = scope.upper()
    # APEX stores scope as a short code: APPLICATION->APP, SESSION->SESS,
    # USER->USER. WWV_FLOW_ITEMS.SCOPE column has max length 6.
    scope_map = {"APPLICATION": "APP", "SESSION": "SESS", "USER": "USER"}
    scope_code = scope_map.get(scope_norm, scope_norm)

    plsql_body = f"""  wwv_flow_imp_shared.create_flow_item(
    p_id => {item_id},
    p_flow_id => {app_id},
    p_name => '{name_esc}',
    p_scope => '{scope_code}',
    p_protection_level => 'N'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_app_item", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "item_id": item_id,
            "name": name,
            "scope": scope_norm,
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
            message=f"apex_add_app_item failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    if not _verify_app_item_exists(profile, app_id, item_id):
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"application item {item_id} not found in "
                f"apex_application_items after create"
            ),
            suggestion="Manual investigation required",
        )

    after, _ = query_metadata_snapshot(profile, app_id)

    export_result = refresh_export(
        sqlcl_conn=profile.sqlcl_name,
        app_id=app_id,
        export_dir=profile.auto_export_dir,
    )

    return {
        "dry_run": False,
        "app_id": app_id,
        "item_id": item_id,
        "name": name,
        "scope": scope_norm,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
