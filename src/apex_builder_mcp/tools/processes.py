"""apex_add_process — DEV-only write tool wrapping wwv_flow_imp_page.create_page_process.

Verification pattern: expected_delta is {} because MetadataSnapshot doesn't
track process counts. Post-write verification queries
apex_application_page_proc directly for the new process_id (id-existence
check). See _verify_process_exists() below.
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
from apex_builder_mcp.tools._write_helpers import (
    query_metadata_snapshot,
    query_workspace_id,
)


def _verify_process_exists(
    profile: Profile, app_id: int, page_id: int, process_id: int
) -> bool:
    """Query apex_application_page_proc to confirm the process was created."""
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select count(*) from apex_application_page_proc "
        f"where application_id = {app_id} and page_id = {page_id} "
        f"and process_id = {process_id};\nexit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    for line in result.stdout.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s) == 1
    return False


@apex_tool(name="apex_add_process", category=Category.WRITE_CORE)
def apex_add_process(
    app_id: int,
    page_id: int,
    process_id: int,
    name: str,
    process_type: str = "NATIVE_PLSQL",
    plsql_code: str = "null;",
    sequence: int = 10,
) -> dict[str, Any]:
    """Add a page process via wwv_flow_imp_page.create_page_process.

    DEV environments only. TEST returns dry-run SQL preview. PROD rejects.
    Wraps the call in wwv_flow_imp.import_begin/import_end (Phase 0 finding).

    Post-write verification: queries apex_application_page_proc by process_id.
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    # Escape single quotes inside plsql code for embedding in PL/SQL string literal.
    code_escaped = plsql_code.replace("'", "''")
    plsql_body = f"""  wwv_flow_imp_page.create_page_process(
    p_id => {process_id},
    p_process_sequence => {sequence},
    p_process_type => '{process_type}',
    p_process_name => '{name}',
    p_process_sql_clob => '{code_escaped}',
    p_flow_id => {app_id},
    p_flow_step_id => {page_id}
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_add_process",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "process_id": process_id,
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
            message=f"apex_add_process failed: {e}",
            suggestion="Check SQL preview via dry_run",
        ) from e

    if not _verify_process_exists(profile, app_id, page_id, process_id):
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"process {process_id} not found in apex_application_page_proc "
                f"after create"
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
        "page_id": page_id,
        "process_id": process_id,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
