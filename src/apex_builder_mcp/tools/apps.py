"""App lifecycle tools (Plan 2B-8).

Implemented
-----------
1. apex_get_app_details(app_id) -> READ_APEX
   Full metadata (30+ columns) from apex_applications view.

2. apex_validate_app(app_id) -> READ_APEX
   Heuristic validation: detects orphan items, regions on missing pages,
   pages with no regions, etc. Returns {ok: bool, issues: [...]}.

3. apex_delete_app(app_id) -> WRITE_CORE
   Calls wwv_flow_imp.remove_flow(p_id) wrapped in an ImportSession.
   DEV-only, destructive.

4. apex_create_app(name, alias, ...) -> WRITE_CORE  (PARTIAL FUNCTIONALITY)
   Creates a minimal application stub via wwv_flow_imp.create_flow + a single
   Home page (page 1). The new app appears in apex_applications and is
   visible in App Builder, BUT the curated minimal call does NOT seed an
   authentication scheme, page templates, theme objects, or navigation list.
   The app is therefore NOT runnable at /ords/r/<alias> until those are
   wired up via App Builder UI ("Create > Authentication Scheme",
   "Themes" subscribe). The result dict has `partial_functionality=True`
   and a `caveat` field describing the limitation.
"""
from __future__ import annotations

import secrets
from typing import Any

from apex_builder_mcp.apex_api.import_session import ImportSession
from apex_builder_mcp.connection.auth_mode import AuthMode, resolve_auth_mode
from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.guard.policy import PolicyContext, enforce_policy
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools._write_helpers import query_workspace_id


def _get_pool() -> Any:
    from apex_builder_mcp.tools.connection import _get_or_create_pool

    return _get_or_create_pool()


def _require_profile() -> Profile:
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    return state.profile


# ---------------------------------------------------------------------------
# 1. apex_get_app_details
# ---------------------------------------------------------------------------


@apex_tool(name="apex_get_app_details", category=Category.READ_APEX)
def apex_get_app_details(app_id: int) -> dict[str, Any]:
    """Full app metadata: 30+ columns from apex_applications.

    Read-only. Uses the oracledb pool. Returns
    `{application_id, found: True, details: {...}}` on hit, or
    `{application_id, found: False}` when the app does not exist.
    """
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select application_id, application_name, alias, pages, owner,
                   workspace, version, build_status, availability_status,
                   authentication_scheme, page_template, compatibility_mode,
                   file_prefix, last_updated_on, last_updated_by, created_on,
                   created_by, theme_number, theme_style_by_user_pref,
                   application_group, application_primary_language,
                   deep_linking, debugging, logo_type, logo_text,
                   nav_bar_type, friendly_url, build_options, image_prefix,
                   home_link
              from apex_applications where application_id = :a
            """,
            a=app_id,
        )
        row = cur.fetchone()
        if row is None:
            return {"application_id": app_id, "found": False}
        cols = [d[0] for d in cur.description]
    details = dict(zip(cols, row, strict=False))
    # Stringify dates so the result is JSON-serializable for FastMCP transport.
    for k, v in list(details.items()):
        if hasattr(v, "isoformat"):
            details[k] = v.isoformat()
    return {
        "application_id": app_id,
        "found": True,
        "details": details,
    }


# ---------------------------------------------------------------------------
# 2. apex_validate_app
# ---------------------------------------------------------------------------


@apex_tool(name="apex_validate_app", category=Category.READ_APEX)
def apex_validate_app(app_id: int) -> dict[str, Any]:
    """Heuristic validation of an APEX application.

    No native APEX 24.2 procedure exposes a holistic validate-application API
    (probed via ALL_ARGUMENTS). Instead this tool runs a few read-only checks
    against `apex_application_pages`, `apex_application_page_regions`, and
    `apex_application_page_items` and reports issues:

      * App not found in apex_applications
      * Page 0 (Global Page) missing
      * Page 1 (Home Page) missing
      * Items whose region_id (item_plug_id) does not exist
      * Pages with zero regions

    Returns {app_id, ok: bool, issues: [...], counts: {...}}.
    """
    pool = _get_pool()
    issues: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    with pool.acquire() as conn:
        cur = conn.cursor()

        # 0. App existence
        cur.execute(
            "select application_name, pages from apex_applications "
            "where application_id = :a",
            a=app_id,
        )
        app_row = cur.fetchone()
        if app_row is None:
            return {
                "app_id": app_id,
                "ok": False,
                "issues": [
                    {
                        "code": "APP_NOT_FOUND",
                        "message": f"application_id={app_id} does not exist",
                    }
                ],
                "counts": {},
            }
        counts["pages_metadata"] = int(app_row[1] or 0)

        # 1. Required well-known pages
        cur.execute(
            "select page_id from apex_application_pages "
            "where application_id = :a and page_id in (0, 1)",
            a=app_id,
        )
        present_required = {int(r[0]) for r in cur.fetchall()}
        for required_pid, label in ((0, "Global Page"), (1, "Home Page")):
            if required_pid not in present_required:
                issues.append(
                    {
                        "code": "MISSING_REQUIRED_PAGE",
                        "page_id": required_pid,
                        "message": f"{label} (page {required_pid}) not found",
                    }
                )

        # 2. Orphan items (item references region not in apex_application_page_regions)
        cur.execute(
            """
            select i.item_id, i.item_name, i.page_id, i.item_plug_id
              from apex_application_page_items i
             where i.application_id = :a
               and i.item_plug_id is not null
               and not exists (
                 select 1 from apex_application_page_regions r
                  where r.application_id = i.application_id
                    and r.region_id = i.item_plug_id
               )
            """,
            a=app_id,
        )
        orphans = cur.fetchall()
        counts["orphan_items"] = len(orphans)
        for r in orphans:
            issues.append(
                {
                    "code": "ORPHAN_ITEM",
                    "item_id": int(r[0]),
                    "item_name": str(r[1]),
                    "page_id": int(r[2]) if r[2] is not None else None,
                    "missing_region_id": int(r[3]) if r[3] is not None else None,
                    "message": (
                        f"item {r[1]!r} on page {r[2]} references "
                        f"missing region_id {r[3]}"
                    ),
                }
            )

        # 3. Pages with zero regions (excluding page 0)
        cur.execute(
            """
            select p.page_id, p.page_name
              from apex_application_pages p
             where p.application_id = :a
               and p.page_id <> 0
               and not exists (
                 select 1 from apex_application_page_regions r
                  where r.application_id = p.application_id
                    and r.page_id = p.page_id
               )
            """,
            a=app_id,
        )
        empty_pages = cur.fetchall()
        counts["pages_without_regions"] = len(empty_pages)
        for r in empty_pages:
            issues.append(
                {
                    "code": "PAGE_NO_REGIONS",
                    "page_id": int(r[0]),
                    "page_name": str(r[1]),
                    "message": f"page {r[0]} ({r[1]!r}) has no regions",
                }
            )

    return {
        "app_id": app_id,
        "ok": len(issues) == 0,
        "issues": issues,
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# 3. apex_delete_app
# ---------------------------------------------------------------------------


def _verify_app_gone(profile: Profile, app_id: int) -> bool:
    """Post-delete verification: confirm app no longer exists."""
    mode = resolve_auth_mode(profile)
    if mode is AuthMode.SQLCL:
        sql = (
            "set heading off feedback off pagesize 0 echo off\n"
            f"select count(*) from apex_applications "
            f"where application_id = {app_id};\n"
            "exit\n"
        )
        result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
        for line in result.cleaned.splitlines():
            s = line.strip()
            if s.isdigit():
                return int(s) == 0
        # If no count parsed, treat as not-verifiable; return False.
        return False
    # password / pool path
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select count(*) from apex_applications where application_id = :a",
            a=app_id,
        )
        row = cur.fetchone()
    return bool(row and int(row[0]) == 0)


@apex_tool(name="apex_delete_app", category=Category.WRITE_CORE)
def apex_delete_app(app_id: int) -> dict[str, Any]:
    """Delete an APEX app via wwv_flow_imp.remove_flow. DEV-only. DESTRUCTIVE.

    Snapshot of app metadata is NOT taken (the app is gone after delete, so
    the standard before/after delta cannot be computed). Instead we verify
    by post-querying apex_applications.
    """
    profile = _require_profile()

    plsql_body = f"  wwv_flow_imp.remove_flow(p_id => {app_id});\n"

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_delete_app",
            is_destructive=True,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "sql_preview": (
                f"-- import_begin/import_end wrap for app {app_id}\n"
                f"-- body:\n{plsql_body}"
            ),
        }

    ws_id = query_workspace_id(profile, profile.workspace)
    sess = ImportSession(
        sqlcl_conn=profile.sqlcl_name,
        workspace_id=ws_id,
        application_id=app_id,
        schema=profile.workspace,
    )
    try:
        sess.execute(plsql_body)
    except Exception as e:
        raise ApexBuilderError(
            code="WRITE_EXEC_FAIL",
            message=f"apex_delete_app failed: {e}",
            suggestion="Check SQL preview via dry_run; the app may still exist.",
        ) from e

    gone = _verify_app_gone(profile, app_id)
    if not gone:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"apex_delete_app: remove_flow returned but application_id={app_id} "
                "still present in apex_applications"
            ),
            suggestion="Manual investigation required",
        )

    return {
        "dry_run": False,
        "app_id": app_id,
        "deleted": True,
    }


# ---------------------------------------------------------------------------
# 4. apex_create_app  (DEFERRED for MVP)
# ---------------------------------------------------------------------------


def _allocate_create_app_id(profile: Profile, workspace: str) -> int:
    """Pick an unused application_id in the workspace, > current max, > 999000."""
    mode = resolve_auth_mode(profile)
    if mode is AuthMode.SQLCL:
        sql = (
            "set heading off feedback off pagesize 0 echo off\n"
            f"select nvl(max(application_id), 0) from apex_applications "
            f"where workspace = '{workspace.upper()}';\n"
            "exit\n"
        )
        result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
        max_id = 0
        for line in result.cleaned.splitlines():
            s = line.strip()
            if s.isdigit():
                max_id = int(s)
                break
    else:
        pool = _get_pool()
        with pool.acquire() as conn:
            cur = conn.cursor()
            cur.execute(
                "select nvl(max(application_id), 0) from apex_applications "
                "where workspace = :w",
                w=workspace.upper(),
            )
            row = cur.fetchone()
        max_id = int(row[0]) if row and row[0] is not None else 0
    return max(max_id + 1, 999001)


def _verify_app_exists(profile: Profile, app_id: int) -> tuple[bool, int]:
    """Post-create verification: returns (exists, page_count)."""
    mode = resolve_auth_mode(profile)
    if mode is AuthMode.SQLCL:
        sql = (
            "set heading off feedback off pagesize 0 echo off\n"
            f"select count(*) from apex_applications where application_id = {app_id};\n"
            f"select pages from apex_applications where application_id = {app_id};\n"
            "exit\n"
        )
        result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
        nums: list[int] = [
            int(s.strip()) for s in result.cleaned.splitlines() if s.strip().isdigit()
        ]
        if not nums:
            return (False, 0)
        if nums[0] == 0:
            return (False, 0)
        return (True, nums[1] if len(nums) >= 2 else 0)
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select count(*), nvl(max(pages), 0) from apex_applications "
            "where application_id = :a",
            a=app_id,
        )
        row = cur.fetchone()
    if not row or int(row[0]) == 0:
        return (False, 0)
    return (True, int(row[1] or 0))


@apex_tool(name="apex_create_app", category=Category.WRITE_CORE)
def apex_create_app(
    name: str,
    alias: str,
    workspace: str | None = None,
    schema: str | None = None,
    app_id: int | None = None,
) -> dict[str, Any]:
    """Create a new APEX application stub. DEV-only. PARTIAL FUNCTIONALITY.

    Wraps `wwv_flow_imp.create_flow` (179 args, all defaulted) with a curated
    minimal subset of params, then seeds a Home page (page 1). The app
    appears in apex_applications and is visible in App Builder, but the
    minimal seed does NOT include:

      * Authentication scheme (app shows blank auth scheme — runtime fails)
      * Page templates / theme objects (page renders unstyled / fails to
        resolve template at runtime)
      * Navigation list

    To get a runnable app, use App Builder UI 'Shared Components > Themes >
    Subscribe Theme' and 'Authentication Schemes > Create' after this tool
    runs, OR (recommended) use App Builder UI 'Create > New Application'
    wizard from the start and drive the app via the rest of this MCP.

    Result includes `partial_functionality=True` to flag the limitation to
    callers.
    """
    profile = _require_profile()

    # Input validation
    if not name or len(name) > 255:
        raise ApexBuilderError(
            code="INVALID_NAME",
            message="name must be 1..255 chars",
            suggestion="Pass a non-empty application name",
        )
    if not alias or len(alias) > 100 or not alias.replace("_", "").isalnum():
        raise ApexBuilderError(
            code="INVALID_ALIAS",
            message="alias must be 1..100 alphanumeric/underscore chars",
            suggestion="Use uppercase identifier-like alias e.g. 'MY_APP'",
        )

    effective_workspace = (workspace or profile.workspace).upper()
    effective_schema = (schema or profile.workspace).upper()
    effective_alias = alias.upper()

    # Allocate app_id if not provided
    new_app_id = app_id if app_id is not None else _allocate_create_app_id(
        profile, effective_workspace
    )

    plsql_body = f"""  wwv_flow_imp.create_flow(
    p_id => {new_app_id},
    p_owner => '{effective_schema}',
    p_name => '{name}',
    p_alias => '{effective_alias}',
    p_application_group => 0,
    p_compatibility_mode => '24.2',
    p_flow_image_prefix => '/i/',
    p_authentication => 'PLUGIN'
  );
  wwv_flow_imp_page.create_page(
    p_id => 1,
    p_name => 'Home',
    p_step_title => 'Home',
    p_autocomplete_on_off => 'OFF',
    p_page_template_options => '#DEFAULT#'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_create_app",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": new_app_id,
            "name": name,
            "alias": effective_alias,
            "workspace": effective_workspace,
            "schema": effective_schema,
            "sql_preview": (
                f"-- import_begin/import_end wrap for new app {new_app_id}\n"
                f"-- body:\n{plsql_body}"
            ),
        }

    ws_id = query_workspace_id(profile, effective_workspace)

    sess = ImportSession(
        sqlcl_conn=profile.sqlcl_name,
        workspace_id=ws_id,
        application_id=new_app_id,
        schema=effective_schema,
    )
    try:
        sess.execute(plsql_body)
    except Exception as e:
        raise ApexBuilderError(
            code="WRITE_EXEC_FAIL",
            message=f"apex_create_app failed: {e}",
            suggestion=(
                "Check SQL preview via dry_run. The app may have been "
                "partially created; verify with apex_get_app_details and "
                "clean up via apex_delete_app if needed."
            ),
        ) from e

    exists, page_count = _verify_app_exists(profile, new_app_id)
    if not exists:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"apex_create_app: create_flow returned but application_id="
                f"{new_app_id} not visible in apex_applications"
            ),
            suggestion="Manual investigation required",
        )

    # Use a token tag so live tests can correlate logs.
    tag = secrets.token_hex(3)

    return {
        "dry_run": False,
        "app_id": new_app_id,
        "name": name,
        "alias": effective_alias,
        "workspace": effective_workspace,
        "schema": effective_schema,
        "page_count": page_count,
        "partial_functionality": True,
        "caveat": (
            "App stub created with minimal create_flow params. NOT runnable at "
            "/ords/r/<alias> until authentication scheme + page templates are "
            "wired via App Builder UI. See docstring for details."
        ),
        "tag": tag,
    }
