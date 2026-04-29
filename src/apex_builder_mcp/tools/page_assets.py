"""Plan 2B-6: page-asset write tools (JS/CSS/static files).

Three tools planned (1 implemented + 2 deferred):

  * apex_add_page_js(app_id, page_id, javascript_code)             [DEFERRED]
      APEX 24.2 exposes NO `update_page` proc surface for setting
      `JAVASCRIPT_CODE` at the page level — `WWV_FLOW_IMP.UPDATE_PAGE`
      params are: p_id, p_flow_id, p_tab_set, p_name, p_step_*,
      p_box_*_text, p_footer_text, p_help_text, p_step_template,
      p_box_image, p_required_role, p_required_patch, p_page_comment.
      No JavaScript / CSS columns exposed.
      The only proc that accepts `p_javascript_code` is
      `WWV_FLOW_IMP_PAGE.CREATE_PAGE`. In import-session context CREATE_PAGE
      is technically an upsert, but empirically (probe page 9101) calling
      `create_page` a second time results in child regions being WIPED
      (regions count went from 1 -> 0 after a re-call). Reproducing all
      child components from scratch would be required and is impractical.
      Workaround: edit page JS via the APEX App Builder UI, or use
      apex_add_static_app_file to ship a JS file referenced by the page.

  * apex_add_app_css(app_id, css_code)                              [DEFERRED]
      APEX 24.2 has NO public proc to set application-level inline CSS.
      `WWV_FLOW_IMP.CREATE_FLOW` param surface includes
      `P_UI_DETECTION_CSS_URLS` but no `P_INLINE_CSS` / `P_CSS_CODE`.
      No `UPDATE_FLOW` / `UPDATE_APPLICATION` proc exists at all
      (verified via ALL_ARGUMENTS).
      Workaround: ship CSS as an app static file via
      apex_add_static_app_file and reference from User Interface
      attributes (Theme Roller / file URLs).

  * apex_add_static_app_file(app_id, file_name, file_content_text,
                              mime_type='text/plain', file_id=None)  [IMPLEMENTED]
      Wraps `WWV_FLOW_IMP_SHARED.CREATE_APP_STATIC_FILE`. Empirically
      verified on app 100. Converts text content to BLOB via
      `utl_raw.cast_to_raw` (requires content <= ~32KB single-RAW limit;
      larger payloads should use a multi-call BLOB build, which is
      deferred to Phase 3). Verification queries
      `apex_application_static_files.application_file_id` by
      (application_id, file_name) tuple.
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

# 30 KB limit for utl_raw.cast_to_raw single-shot payloads
# (Oracle RAW max is 32767 bytes; we leave a safety margin for UTF-8 expansion).
_MAX_INLINE_TEXT_BYTES = 30 * 1024


# ---------------------------------------------------------------------------
# Verification helper
# ---------------------------------------------------------------------------


def _verify_static_file_exists(
    profile: Profile, app_id: int, file_name: str
) -> bool:
    name_esc = file_name.replace("'", "''")
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select count(*) from apex_application_static_files "
        f"where application_id = {app_id} and file_name = '{name_esc}';\nexit\n"
    )
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    for line in result.cleaned.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s) >= 1
    return False


# ---------------------------------------------------------------------------
# Deferred: apex_add_page_js
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_page_js", category=Category.WRITE_CORE)
def apex_add_page_js(
    app_id: int,
    page_id: int,
    javascript_code: str,
) -> dict[str, Any]:
    """[DEFERRED for MVP] Set page-level JavaScript via app_builder_api.

    APEX 24.2 has no proc that updates `JAVASCRIPT_CODE` on an existing page
    without re-creating the page (which wipes children). Empirically verified
    via probe page 9101 — re-calling wwv_flow_imp_page.create_page wiped the
    region count from 1 to 0.

    Workarounds:
      1. Use the APEX App Builder UI (Page Designer > JavaScript section).
      2. Use apex_add_static_app_file to ship a JS file, then reference it
         via Page > JavaScript > File URLs.
    """
    raise ApexBuilderError(
        code="TOOL_DEFERRED",
        message="apex_add_page_js not implemented in MVP",
        suggestion=(
            "APEX 24.2 has no UPDATE proc for page JavaScript_code; the only "
            "entry point is CREATE_PAGE, which (per empirical 2B-6 probe) "
            "wipes child regions. Use App Builder UI or ship JS via "
            "apex_add_static_app_file + reference URL on the page. "
            "Full page-attribute update deferred to Phase 3."
        ),
    )


# ---------------------------------------------------------------------------
# Deferred: apex_add_app_css
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_app_css", category=Category.WRITE_CORE)
def apex_add_app_css(app_id: int, css_code: str) -> dict[str, Any]:
    """[DEFERRED for MVP] Add application-level inline CSS.

    APEX 24.2 has no proc surface for application-level inline CSS:
      * WWV_FLOW_IMP.CREATE_FLOW has only P_UI_DETECTION_CSS_URLS (URLs)
        and no P_INLINE_CSS / P_CSS_CODE.
      * No UPDATE_FLOW / UPDATE_APPLICATION proc exists at all
        (verified via ALL_ARGUMENTS).

    Workaround: ship the CSS as an application static file via
    apex_add_static_app_file, then reference its URL from User Interface
    > Theme Roller > Custom CSS, or via Page > CSS File URLs.
    """
    raise ApexBuilderError(
        code="TOOL_DEFERRED",
        message="apex_add_app_css not implemented in MVP",
        suggestion=(
            "APEX 24.2 has no public proc for application-level inline CSS. "
            "Ship CSS via apex_add_static_app_file and reference its URL "
            "from User Interface attributes (Theme Roller / Page File URLs). "
            "Application-level CSS update deferred to Phase 3."
        ),
    )


# ---------------------------------------------------------------------------
# Implemented: apex_add_static_app_file
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_static_app_file", category=Category.WRITE_CORE)
def apex_add_static_app_file(
    app_id: int,
    file_name: str,
    file_content_text: str,
    mime_type: str = "text/plain",
    file_id: int | None = None,
) -> dict[str, Any]:
    """Upload a static application file (CSS, JS, font, etc.).

    Wraps WWV_FLOW_IMP_SHARED.CREATE_APP_STATIC_FILE. DEV-only.
    TEST returns dry-run preview. PROD rejects.

    Content size limit: ~30 KB (Oracle RAW max minus safety margin).
    Larger files require chunked LOB construction — deferred to Phase 3.

    Verification: queries apex_application_static_files by
    (application_id, file_name).
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    # Size check (UTF-8 byte length)
    content_bytes = file_content_text.encode("utf-8")
    if len(content_bytes) > _MAX_INLINE_TEXT_BYTES:
        raise ApexBuilderError(
            code="CONTENT_TOO_LARGE",
            message=(
                f"file_content_text is {len(content_bytes)} bytes; "
                f"limit is {_MAX_INLINE_TEXT_BYTES} bytes"
            ),
            suggestion=(
                "Split into multiple static files, or wait for chunked-BLOB "
                "support (Phase 3)."
            ),
        )

    name_esc = file_name.replace("'", "''")
    mime_esc = mime_type.replace("'", "''")
    content_esc = file_content_text.replace("'", "''")
    id_clause = f"p_id => {file_id}, " if file_id is not None else ""

    plsql_body = f"""  declare
    v_blob blob;
  begin
    v_blob := utl_raw.cast_to_raw('{content_esc}');
    wwv_flow_imp_shared.create_app_static_file(
      {id_clause}p_flow_id => {app_id},
      p_file_name => '{name_esc}',
      p_mime_type => '{mime_esc}',
      p_file_charset => 'utf-8',
      p_file_content => v_blob
    );
  end;
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_add_static_app_file",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "file_name": file_name,
            "mime_type": mime_type,
            "content_bytes": len(content_bytes),
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
            message=f"apex_add_static_app_file failed: {e}",
            suggestion=(
                "Check SQL preview via dry_run; verify content has no "
                "embedded NULs or invalid UTF-8 sequences."
            ),
        ) from e

    if not _verify_static_file_exists(profile, app_id, file_name):
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=(
                f"static file {file_name!r} not found in "
                f"apex_application_static_files after create"
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
        "file_name": file_name,
        "mime_type": mime_type,
        "content_bytes": len(content_bytes),
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
