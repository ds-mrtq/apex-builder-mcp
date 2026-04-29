"""Shared read helpers for write tools (apex_add_page/region/item).

These helpers branch on `auth_mode` so the SAME write tool code works under:

  * `auth_mode=sqlcl`   — primary/default path. Reads via SQLcl subprocess
                          (`sql -name <conn>`). No oracledb pool needed.
  * `auth_mode=password` — fallback. Reads via the configured oracledb pool.

Both paths must return identical-shape values so the calling tool code is
oblivious to which path was taken.
"""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.auth_mode import AuthMode, resolve_auth_mode
from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile


def _get_pool() -> Any:
    """Lazy import to avoid circular dep at module load time."""
    from apex_builder_mcp.tools.connection import _get_or_create_pool

    return _get_or_create_pool()


# ---------------------------------------------------------------------------
# SQLcl subprocess path
# ---------------------------------------------------------------------------


def _query_workspace_id_sqlcl(profile: Profile, workspace: str) -> int:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select workspace_id from apex_workspaces "
        f"where upper(workspace) = '{workspace.upper()}';\n"
        "exit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    if result.rc != 0:
        raise ApexBuilderError(
            code="SQLCL_QUERY_FAIL",
            message=f"workspace_id lookup via SQLcl failed: rc={result.rc}",
            suggestion=f"Check sqlcl saved connection '{profile.sqlcl_name}'",
        )
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s)
    raise ApexBuilderError(
        code="WORKSPACE_NOT_FOUND",
        message=f"workspace {workspace!r} not found",
        suggestion="Verify workspace name with apex_describe_app or check apex_workspaces view",
    )


def _query_metadata_snapshot_sqlcl(
    profile: Profile, app_id: int
) -> tuple[MetadataSnapshot, str]:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select pages from apex_applications where application_id = {app_id};\n"
        f"select count(*) from apex_application_page_regions where application_id = {app_id};\n"
        f"select count(*) from apex_application_page_items where application_id = {app_id};\n"
        f"select alias from apex_applications where application_id = {app_id};\n"
        "exit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    if result.rc != 0:
        raise ApexBuilderError(
            code="SQLCL_QUERY_FAIL",
            message=f"metadata snapshot via SQLcl failed: rc={result.rc}",
            suggestion=f"Check sqlcl saved connection '{profile.sqlcl_name}'",
        )
    body = result.cleaned
    nums: list[int] = [
        int(s.strip()) for s in body.splitlines() if s.strip().isdigit()
    ]
    if len(nums) < 3:
        raise ApexBuilderError(
            code="APP_NOT_FOUND",
            message=f"application_id={app_id} not found",
            suggestion="Verify with apex_list_apps or apex_describe_app",
        )
    alias = ""
    for line in body.splitlines():
        s = line.strip()
        if s and not s.isdigit():
            alias = s
            break
    return (
        MetadataSnapshot(pages=nums[0], regions=nums[1], items=nums[2]),
        alias,
    )


# ---------------------------------------------------------------------------
# oracledb pool path (auth_mode=password)
# ---------------------------------------------------------------------------


def _query_workspace_id_pool(workspace: str) -> int:
    pool = _get_pool()
    with pool.acquire() as conn:
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
            suggestion="Verify workspace name with apex_describe_app or check apex_workspaces view",
        )
    return int(row[0])


def _query_metadata_snapshot_pool(app_id: int) -> tuple[MetadataSnapshot, str]:
    pool = _get_pool()
    with pool.acquire() as conn:
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
            suggestion="Verify with apex_list_apps or apex_describe_app",
        )
    return (
        MetadataSnapshot(pages=int(row[0]), regions=int(row[1]), items=int(row[2])),
        str(row[3]) if row[3] else "",
    )


# ---------------------------------------------------------------------------
# Public API: branch on auth_mode
# ---------------------------------------------------------------------------


def query_workspace_id(profile: Profile, workspace: str) -> int:
    """Look up workspace_id for the given workspace name.

    Branches on `profile.auth_mode`:
      * sqlcl    -> SQLcl subprocess
      * password -> oracledb pool
    """
    mode = resolve_auth_mode(profile)
    if mode is AuthMode.SQLCL:
        return _query_workspace_id_sqlcl(profile, workspace)
    return _query_workspace_id_pool(workspace)


def query_metadata_snapshot(
    profile: Profile, app_id: int
) -> tuple[MetadataSnapshot, str]:
    """Get metadata snapshot + alias for a given app.

    Branches on `profile.auth_mode`:
      * sqlcl    -> SQLcl subprocess
      * password -> oracledb pool
    """
    mode = resolve_auth_mode(profile)
    if mode is AuthMode.SQLCL:
        return _query_metadata_snapshot_sqlcl(profile, app_id)
    return _query_metadata_snapshot_pool(app_id)
