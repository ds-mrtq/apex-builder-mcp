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

import re
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


# Regex matches a top-level ORDER BY clause at the tail of a query.
# Multiline + case-insensitive; tolerates trailing semicolon / whitespace.
# Conservative: only strips ORDER BY that appears AFTER the last FROM, so a
# subquery ORDER BY inside a derived table won't trigger (those are rare and
# the heuristic prefers false negatives over false positives).
_ORDER_BY_TAIL_RE = re.compile(
    r"\s+ORDER\s+BY\s+[^()]*?\s*;?\s*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _has_trailing_order_by(sql: str) -> bool:
    """True if the SQL ends with an ORDER BY clause (APEX IG rejects this)."""
    return bool(_ORDER_BY_TAIL_RE.search(sql))


def _build_region_column_block(
    region_col_id: int,
    app_id: int,
    page_id: int,
    region_id: int,
    col_name: str,
    col_data_type: str,
    display_seq: int,
) -> str:
    """Emit a wwv_flow_imp_page.create_region_column call for one IG column.

    Required APEX 24.2 params (from ALL_ARGUMENTS): P_NAME, P_DISPLAY_SEQUENCE.
    We pass P_ID + P_FLOW_ID + P_PAGE_ID + P_REGION_ID so APEX can wire the
    FK to the parent region, plus P_DATA_TYPE / P_SOURCE_TYPE='DB_COLUMN' /
    P_SOURCE_EXPRESSION so the column metadata is complete enough that the
    downstream create_ig_report_column can reference it without NULL FKs.
    """
    n = col_name.replace("'", "''")
    dt = col_data_type.replace("'", "''")
    return f"""  wwv_flow_imp_page.create_region_column(
    p_id => {region_col_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_region_id => {region_id},
    p_name => '{n}',
    p_source_type => 'DB_COLUMN',
    p_source_expression => '{n}',
    p_data_type => '{dt}',
    p_heading => '{n}',
    p_label => '{n}',
    p_display_sequence => {display_seq}
  );
"""


def _build_ig_report_column_block(
    ig_report_col_id: int,
    view_id: int,
    region_col_id: int,
    display_seq: int,
) -> str:
    """Emit wwv_flow_imp_page.create_ig_report_column for one IG column in one view.

    Required APEX 24.2 params: P_VIEW_ID, P_DISPLAY_SEQ. P_COLUMN_ID is
    defaulted but MUST be set explicitly so the per-view column references
    the parent region column row (created via create_region_column) —
    otherwise WWV_FLOW_IG_REPORT_COLUMNS.column_id is NULL and Page
    Designer Save raises ORA-01400 (Bug #2c).
    """
    return f"""  wwv_flow_imp_page.create_ig_report_column(
    p_id => {ig_report_col_id},
    p_view_id => {view_id},
    p_column_id => {region_col_id},
    p_display_seq => {display_seq}
  );
"""


@apex_tool(name="apex_add_interactive_grid", category=Category.WRITE_CORE)
def apex_add_interactive_grid(
    app_id: int,
    page_id: int,
    region_id: int,
    sql_query: str,
    name: str,
    columns: list[dict[str, str]] | None = None,
    template_id: int = 0,
    display_sequence: int = 10,
) -> dict[str, Any]:
    """Add a NATIVE_IG (interactive grid) region with default report+view. DEV-only.

    When ``columns`` is supplied (recommended), composes the full IG metadata
    graph in a single ImportSession PL/SQL body:
      1. create_page_plug          -> the IG region (source_type='NATIVE_IG')
      2. create_region_column      -> per data column (Bug #2c fix)
      3. create_interactive_grid   -> IG component metadata
      4. create_ig_report          -> 'Primary Report' (type=PRIMARY, default_view=GRID)
      5. create_ig_report_view     -> the default GRID view
      6. create_ig_report_column   -> per data column linked to view (Bug #2c fix)

    When ``columns`` is None (legacy), only steps 1, 3, 4, 5 fire — the IG
    will render ORA-01403 at runtime and Page Designer Save raises ORA-01400
    on WWV_FLOW_IG_REPORT_COLUMNS. Caller gets a warning in the response.

    Args:
      app_id, page_id, region_id: target IDs.
      sql_query: SELECT statement for the IG source.
      name: display name for the region.
      columns: list of {"name": str, "data_type": str} dicts describing the
        SELECT clause columns in order. data_type values: 'VARCHAR2', 'NUMBER',
        'DATE', 'TIMESTAMP', 'CLOB'. When supplied, this drives full metadata
        seeding so Save works without UI repair. Example:
        [{"name": "lane_code", "data_type": "VARCHAR2"},
         {"name": "step_code", "data_type": "VARCHAR2"},
         {"name": "display_order", "data_type": "NUMBER"}]
      template_id, display_sequence: region rendering settings.

    Derived ids (so caller supplies only region_id):
      ig_id     = region_id
      report_id = region_id + 1
      view_id   = region_id + 2
      region_col_ids   = region_id*1000 + 0, 1, 2, ...   (one per column)
      ig_report_col_ids= region_id*1000 + 500, 501, 502, ... (offset 500)

    sql_query constraints:
      - ORDER BY at the end is REJECTED (APEX IG validates and rejects this).
        Tool raises IG_SQL_HAS_ORDER_BY before any PL/SQL runs.

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

    # Bug #1 (HT_AMMS 2026-05-20): APEX IG validates SQL and rejects ORDER BY
    # at save time. Without this guard the tool reports success while the
    # region is created in a broken state (ORA-01403 at runtime + RED in
    # Page Designer). Reject early with a clear suggestion.
    if _has_trailing_order_by(sql_query):
        raise ApexBuilderError(
            code="IG_SQL_HAS_ORDER_BY",
            message=(
                "Interactive Grid sql_query must NOT end with ORDER BY — "
                "APEX IG uses column-level sorting instead and rejects the "
                "SQL at save time (you'd see a RED region in Page Designer "
                "and ORA-01403 at runtime)."
            ),
            suggestion=(
                "Remove the trailing ORDER BY clause from sql_query. "
                "Configure default sort order via IG column metadata "
                "(p_sort_order / p_sort_direction on create_ig_report_column) "
                "or in the App Builder UI Column attributes."
            ),
            sql_attempted=sql_query,
        )

    ig_id = region_id
    report_id = region_id + 1
    view_id = region_id + 2

    # Validate columns list (if supplied) — fail-fast before any PL/SQL.
    _ALLOWED_DATA_TYPES = {"VARCHAR2", "NUMBER", "DATE", "TIMESTAMP", "CLOB"}
    if columns is not None:
        if not columns:
            raise ApexBuilderError(
                code="IG_COLUMNS_EMPTY",
                message="columns=[] is not allowed — pass None to skip column seeding, or supply at least one column dict.",
                suggestion="Either omit the columns argument (legacy bare-IG, Bug #2c) or supply non-empty [{'name':..., 'data_type':...}, ...].",
            )
        for i, col in enumerate(columns):
            n = col.get("name")
            dt = (col.get("data_type") or "").upper()
            if not n:
                raise ApexBuilderError(
                    code="IG_COLUMNS_BAD_NAME",
                    message=f"columns[{i}] missing 'name'",
                    suggestion="Each column dict must have a non-empty 'name'.",
                )
            if dt not in _ALLOWED_DATA_TYPES:
                raise ApexBuilderError(
                    code="IG_COLUMNS_BAD_TYPE",
                    message=f"columns[{i}] data_type={col.get('data_type')!r} unsupported",
                    suggestion=f"Allowed data_type values: {sorted(_ALLOWED_DATA_TYPES)}.",
                )

    # Escape single quotes in sql_query for embedding
    sql_escaped = sql_query.replace("'", "''")

    # Block 1: region container
    blocks: list[str] = [f"""  wwv_flow_imp_page.create_page_plug(
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
"""]

    # Block 2 (Bug #2c fix): one create_region_column per data column
    if columns is not None:
        for i, col in enumerate(columns):
            blocks.append(_build_region_column_block(
                region_col_id=region_id * 1000 + i,
                app_id=app_id,
                page_id=page_id,
                region_id=region_id,
                col_name=col["name"],
                col_data_type=col["data_type"].upper(),
                display_seq=(i + 1) * 10,
            ))

    # Block 3-5: IG component + report + view
    blocks.append(f"""  wwv_flow_imp_page.create_interactive_grid(
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
""")

    # Block 6 (Bug #2c fix): one create_ig_report_column per data column,
    # linking each per-view column to its parent region column.
    if columns is not None:
        for i, _ in enumerate(columns):
            blocks.append(_build_ig_report_column_block(
                ig_report_col_id=region_id * 1000 + 500 + i,
                view_id=view_id,
                region_col_id=region_id * 1000 + i,
                display_seq=(i + 1) * 10,
            ))

    plsql_body = "".join(blocks)

    # Warning surfaced both in dry-run and live responses when caller skips
    # column metadata. The resulting IG cannot Save from Page Designer
    # without raising ORA-01400 — see Bug #2c.
    warnings: list[str] = []
    if columns is None:
        warnings.append(
            "columns=None: IG region created without per-column metadata. "
            "Save from Page Designer will raise ORA-01400 on "
            "WWV_FLOW_IG_REPORT_COLUMNS (Bug #2c). Pass columns=[{'name':..., "
            "'data_type':...}, ...] to seed the full metadata graph."
        )
    column_count = len(columns) if columns is not None else 0

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
            "column_count": column_count,
            "warnings": warnings,
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
        "column_count": column_count,
        "warnings": warnings,
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
