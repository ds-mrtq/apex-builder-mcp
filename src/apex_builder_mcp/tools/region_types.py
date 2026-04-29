"""Region-type write tools for Plan 2B-3.

Implements two region-type creation tools, defers two more.

Implemented:
  * apex_add_form_region(app_id, page_id, region_id, table_name, name)
      Creates a NATIVE_FORM region bound to a table (single-row CRUD).
      Uses wwv_flow_imp_page.create_page_plug with p_plug_source_type='NATIVE_FORM',
      p_query_type='TABLE', p_query_table=table_name. expected_delta={"regions": 1}.

  * apex_add_interactive_grid(app_id, page_id, region_id, sql_query, name)
      Creates a NATIVE_IG region with default IG report + grid view.
      Composes 3 procs in one ImportSession PL/SQL body:
        - wwv_flow_imp_page.create_page_plug (the region, source_type='NATIVE_IG')
        - wwv_flow_imp_page.create_interactive_grid (the IG metadata)
        - wwv_flow_imp_page.create_ig_report (the default 'Primary Report')
        - wwv_flow_imp_page.create_ig_report_view (the GRID view)
      Required-args discovery (Phase 2B-3):
        CREATE_INTERACTIVE_GRID  - all defaulted (we still pass id+region_id+flow+page)
        CREATE_IG_REPORT         - p_interactive_grid_id, p_type, p_default_view
        CREATE_IG_REPORT_VIEW    - p_report_id, p_view_type
      Advanced features (column controls, filters, master-detail link, custom
      report views beyond default GRID) are deferred to Phase 3 and must be
      configured via the App Builder UI for now.

Deferred (TOOL_DEFERRED):
  * apex_add_interactive_report - composing wwv_flow_imp_page.create_worksheet +
      create_worksheet_column (per column) + create_worksheet_rpt is even more
      complex than IG; per-column metadata makes it impractical without
      column-name discovery from sql_query. Phase 3.
  * apex_add_master_detail - composes 2 IGs with link relationship; depends on
      IG infrastructure stability + extra master_region_id/filtered_region_id
      wiring. Phase 3.

NOTE on id derivation: The IG report id and view id must be unique within
the application. We use derived ids so the caller only supplies region_id:
  ig_id     = region_id (the IG component id matches the region)
  report_id = region_id + 1
  view_id   = region_id + 2
This mirrors APEX export conventions and keeps the call site simple.
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

# ---------------------------------------------------------------------------
# Implemented: apex_add_form_region
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_form_region", category=Category.WRITE_CORE)
def apex_add_form_region(
    app_id: int,
    page_id: int,
    region_id: int,
    table_name: str,
    name: str,
    template_id: int = 0,
    display_sequence: int = 10,
) -> dict[str, Any]:
    """Add a NATIVE_FORM region (single-row CRUD on a table). DEV-only.

    Uses wwv_flow_imp_page.create_page_plug with
      p_plug_source_type='NATIVE_FORM'
      p_query_type='TABLE'
      p_query_table=table_name
      p_query_owner=<workspace schema>

    Caller is responsible for adding individual page items (P_ITEM) bound to
    table columns afterward (e.g. via apex_bulk_add_items). The form region
    itself is the container plug; APEX form-region behavior (auto-fetch on
    page load, auto-save on submit) is driven by associated page processes
    (Form - Initialization, Form - Automatic Row Processing) which are NOT
    auto-created here. Add them separately via apex_add_process if you need
    full CRUD wiring.

    expected_delta = {"regions": 1}
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    plsql_body = f"""  wwv_flow_imp_page.create_page_plug(
    p_id => {region_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_plug_name => '{name}',
    p_plug_template => {template_id},
    p_plug_display_sequence => {display_sequence},
    p_plug_source_type => 'NATIVE_FORM',
    p_query_type => 'TABLE',
    p_query_table => '{table_name}',
    p_query_owner => '{profile.workspace}'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_form_region", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
            "table_name": table_name,
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
            message=f"apex_add_form_region failed: {e}",
            suggestion="Check SQL preview via dry_run; verify table exists in workspace schema",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"regions": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"form region write completed but metadata mismatch: {reason}",
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
        "table_name": table_name,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }


# ---------------------------------------------------------------------------
# Implemented (minimal): apex_add_interactive_grid
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_interactive_grid", category=Category.WRITE_CORE)
def apex_add_interactive_grid(
    app_id: int,
    page_id: int,
    region_id: int,
    sql_query: str,
    name: str,
    template_id: int = 0,
    display_sequence: int = 10,
) -> dict[str, Any]:
    """Add a NATIVE_IG (interactive grid) region with default report+view. DEV-only.

    Composes four create_* calls in a single ImportSession PL/SQL body:
      1. create_page_plug          -> the IG region (source_type='NATIVE_IG')
      2. create_interactive_grid   -> IG component metadata
      3. create_ig_report          -> 'Primary Report' (type=PRIMARY,
                                      default_view=GRID)
      4. create_ig_report_view     -> the default GRID view

    Derived ids (kept simple so caller supplies only region_id):
      ig_id     = region_id          (the IG matches the region)
      report_id = region_id + 1
      view_id   = region_id + 2

    APEX 24.2 required args (Phase 2B-3 ALL_ARGUMENTS discovery):
      CREATE_INTERACTIVE_GRID  - all params defaulted; we still pass
                                 p_id+p_flow_id+p_page_id+p_region_id.
      CREATE_IG_REPORT         - p_interactive_grid_id, p_type, p_default_view
      CREATE_IG_REPORT_VIEW    - p_report_id, p_view_type

    Advanced features (column controls per column, filters, master-detail
    relationships, multiple report views) require additional create_ig_* calls
    and per-column metadata; deferred to Phase 3. Configure via App Builder UI
    after this tool seeds the base IG.

    expected_delta = {"regions": 1}
    """
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    profile = state.profile

    ig_id = region_id
    report_id = region_id + 1
    view_id = region_id + 2

    # Escape single quotes in sql_query for embedding
    sql_escaped = sql_query.replace("'", "''")

    plsql_body = f"""  wwv_flow_imp_page.create_page_plug(
    p_id => {region_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_plug_name => '{name}',
    p_plug_template => {template_id},
    p_plug_display_sequence => {display_sequence},
    p_plug_source_type => 'NATIVE_IG',
    p_query_type => 'SQL',
    p_plug_source => '{sql_escaped}'
  );
  wwv_flow_imp_page.create_interactive_grid(
    p_id => {ig_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_region_id => {region_id}
  );
  wwv_flow_imp_page.create_ig_report(
    p_id => {report_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_interactive_grid_id => {ig_id},
    p_type => 'PRIMARY',
    p_default_view => 'GRID'
  );
  wwv_flow_imp_page.create_ig_report_view(
    p_id => {view_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_report_id => {report_id},
    p_view_type => 'GRID'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_interactive_grid", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
            "ig_id": ig_id,
            "report_id": report_id,
            "view_id": view_id,
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
            message=f"apex_add_interactive_grid failed: {e}",
            suggestion="Check SQL preview via dry_run; verify sql_query is valid",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"regions": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"IG region write completed but metadata mismatch: {reason}",
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
        "ig_id": ig_id,
        "report_id": report_id,
        "view_id": view_id,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }


# ---------------------------------------------------------------------------
# Deferred: apex_add_interactive_report
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_interactive_report", category=Category.WRITE_CORE)
def apex_add_interactive_report(
    app_id: int,
    page_id: int,
    region_id: int,
    sql_query: str,
    name: str,
) -> dict[str, Any]:
    """[DEFERRED for MVP] Use apex_add_region with NATIVE_IR + App Builder UI.

    APEX 24.2 IR creation requires composing wwv_flow_imp_page.create_worksheet +
    create_worksheet_column (per column from sql_query, requires column-name
    discovery) + create_worksheet_rpt + create_worksheet_condition + ...
    Per-column metadata is impractical without parsing the sql_query AST or
    executing it to get cursor descriptions. Deferred to Phase 3.

    Workaround: call apex_add_region(source_type='NATIVE_IR', ...) to create
    the bare IR region, then configure columns and default report via the
    App Builder UI.
    """
    raise ApexBuilderError(
        code="TOOL_DEFERRED",
        message="apex_add_interactive_report not implemented in MVP",
        suggestion=(
            "Use apex_add_region with source_type='NATIVE_IR' to create the bare "
            "region, then configure columns + default report via App Builder UI. "
            "Full IR seeding deferred to Phase 3."
        ),
    )


# ---------------------------------------------------------------------------
# Deferred: apex_add_master_detail
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_master_detail", category=Category.WRITE_CORE)
def apex_add_master_detail(
    app_id: int,
    page_id: int,
    master_region_id: int,
    detail_region_id: int,
    master_table: str,
    detail_table: str,
    link_column: str,
    name: str,
) -> dict[str, Any]:
    """[DEFERRED for MVP] Compose two apex_add_interactive_grid calls + master_region_id link.

    Master-detail relationships in APEX 24.2 require:
      1. Two IG regions (master + detail) - depends on apex_add_interactive_grid
      2. wwv_flow_imp_page.create_page_plug for detail with
         p_master_region_id => <master_region_id> and p_filtered_region_id wiring
      3. Linking column metadata via create_ig_column_link or similar
      4. Auto-row-fetch processes wired between regions

    Steps 3-4 are not exposed by single APEX procs and require deeper
    component wiring. Deferred to Phase 3 alongside full IG/IR feature support.

    Workaround: create two IGs via apex_add_interactive_grid, then wire the
    master-detail relationship via App Builder UI (Region > Master Region
    attribute) for now.
    """
    raise ApexBuilderError(
        code="TOOL_DEFERRED",
        message="apex_add_master_detail not implemented in MVP",
        suggestion=(
            "Create two IGs separately via apex_add_interactive_grid, then wire "
            "master-detail via App Builder UI (Region > Master Region attribute). "
            "Full master-detail composition deferred to Phase 3."
        ),
    )
