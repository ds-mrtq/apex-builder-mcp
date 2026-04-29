"""Region-type write tools for Plan 2B-4.

Implements three region-type creation tools (charts, cards, calendar).

Implemented:
  * apex_add_jet_chart(app_id, page_id, region_id, sql_query, name, chart_type='bar')
      Composes 3 procs in one ImportSession PL/SQL body:
        - wwv_flow_imp_page.create_page_plug    -> the chart region
                                                   (source_type='NATIVE_JET_CHART_V2')
        - wwv_flow_imp_page.create_jet_chart    -> JET chart metadata
                                                   (p_chart_type defaulted to 'bar')
        - wwv_flow_imp_page.create_jet_chart_series -> default series bound to sql_query
      Required-args discovery (Phase 2B-4 ALL_ARGUMENTS):
        CREATE_JET_CHART        - all 80 params defaulted
        CREATE_JET_CHART_SERIES - all 118 params defaulted
      Derived ids (caller supplies only region_id):
        chart_id  = region_id
        series_id = region_id + 1

  * apex_add_metric_cards(app_id, page_id, region_id, sql_query, name)
      Composes 2 procs:
        - wwv_flow_imp_page.create_page_plug    -> region with source_type='NATIVE_CARDS'
        - wwv_flow_imp_page.create_card         -> card-attribute defaults (LAYOUT_TYPE='GRID')
      Required-args discovery: CREATE_CARD has 52 params, all defaulted.
      The card column-name bindings (title/body) are left to App Builder UI for
      MVP; this tool seeds the bare cards region + minimal card-attribute row so
      APEX renders without errors.

  * apex_add_calendar(app_id, page_id, region_id, sql_query, name, date_column='START_DATE')
      Direct call to wwv_flow_imp_page.create_calendar (123 params, all defaulted).
      The proc creates BOTH the page-plug region AND the calendar-source row in one
      call (it embeds plug fields like p_plug_name, p_plug_template, etc.).
      We pass p_id => region_id so verify_post_success on regions delta still works.

NOTE on id derivation: The chart series id and card id must be unique within
the application. We use derived ids (region_id + offset) so the caller only
supplies region_id. This mirrors APEX export conventions.
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
# Implemented: apex_add_jet_chart
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_jet_chart", category=Category.WRITE_CORE)
def apex_add_jet_chart(
    app_id: int,
    page_id: int,
    region_id: int,
    sql_query: str,
    name: str,
    chart_type: str = "bar",
    template_id: int = 0,
    display_sequence: int = 10,
) -> dict[str, Any]:
    """Add a NATIVE_JET_CHART_V2 region with one default series. DEV-only.

    Composes three create_* calls in a single ImportSession PL/SQL body:
      1. create_page_plug         -> the chart region
                                     (p_plug_source_type='NATIVE_JET_CHART_V2')
      2. create_jet_chart         -> JET chart metadata (p_chart_type)
      3. create_jet_chart_series  -> default series with SQL data source

    Derived ids (caller supplies only region_id):
      chart_id  = region_id
      series_id = region_id + 1

    APEX 24.2 required args (Phase 2B-4 ALL_ARGUMENTS discovery):
      CREATE_JET_CHART         - all 80 params defaulted
      CREATE_JET_CHART_SERIES  - all 118 params defaulted

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

    chart_id = region_id
    series_id = region_id + 1

    sql_escaped = sql_query.replace("'", "''")
    name_esc = name.replace("'", "''")
    chart_type_esc = chart_type.replace("'", "''")

    plsql_body = f"""  wwv_flow_imp_page.create_page_plug(
    p_id => {region_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_plug_name => '{name_esc}',
    p_plug_template => {template_id},
    p_plug_display_sequence => {display_sequence},
    p_plug_source_type => 'NATIVE_JET_CHART_V2',
    p_query_type => 'SQL',
    p_plug_source => '{sql_escaped}'
  );
  wwv_flow_imp_page.create_jet_chart(
    p_id => {chart_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_region_id => {region_id},
    p_chart_type => '{chart_type_esc}'
  );
  wwv_flow_imp_page.create_jet_chart_series(
    p_id => {series_id},
    p_chart_id => {chart_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_seq => 10,
    p_name => '{name_esc}',
    p_data_source_type => 'REGION_SOURCE'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_jet_chart", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
            "chart_id": chart_id,
            "series_id": series_id,
            "chart_type": chart_type,
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
            message=f"apex_add_jet_chart failed: {e}",
            suggestion="Check SQL preview via dry_run; verify sql_query is valid",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"regions": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"chart region write completed but metadata mismatch: {reason}",
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
        "chart_id": chart_id,
        "series_id": series_id,
        "chart_type": chart_type,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }


# ---------------------------------------------------------------------------
# Implemented: apex_add_metric_cards
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_metric_cards", category=Category.WRITE_CORE)
def apex_add_metric_cards(
    app_id: int,
    page_id: int,
    region_id: int,
    sql_query: str,
    name: str,
    template_id: int = 0,
    display_sequence: int = 10,
) -> dict[str, Any]:
    """Add a NATIVE_CARDS region with default card-attribute row. DEV-only.

    Composes two procs in one ImportSession:
      1. create_page_plug -> region with source_type='NATIVE_CARDS', p_query_type='SQL'
      2. create_card      -> minimal card-attribute row (LAYOUT_TYPE='GRID')

    Card column-name bindings (title/body/icon mapping to sql_query columns)
    are left to App Builder UI for MVP. This tool seeds a bare cards region
    that APEX can render; users configure column mappings via the UI.

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

    card_id = region_id  # CREATE_CARD's p_id is its own row id; reuse region_id

    sql_escaped = sql_query.replace("'", "''")
    name_esc = name.replace("'", "''")

    plsql_body = f"""  wwv_flow_imp_page.create_page_plug(
    p_id => {region_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_plug_name => '{name_esc}',
    p_plug_template => {template_id},
    p_plug_display_sequence => {display_sequence},
    p_plug_source_type => 'NATIVE_CARDS',
    p_query_type => 'SQL',
    p_plug_source => '{sql_escaped}'
  );
  wwv_flow_imp_page.create_card(
    p_id => {card_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_region_id => {region_id},
    p_layout_type => 'GRID'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_metric_cards", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
            "card_id": card_id,
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
            message=f"apex_add_metric_cards failed: {e}",
            suggestion="Check SQL preview via dry_run; verify sql_query is valid",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"regions": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"cards region write completed but metadata mismatch: {reason}",
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
        "card_id": card_id,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }


# ---------------------------------------------------------------------------
# Implemented: apex_add_calendar
# ---------------------------------------------------------------------------


@apex_tool(name="apex_add_calendar", category=Category.WRITE_CORE)
def apex_add_calendar(
    app_id: int,
    page_id: int,
    region_id: int,
    sql_query: str,
    name: str,
    date_column: str = "START_DATE",
    template_id: int = 0,
    display_sequence: int = 10,
) -> dict[str, Any]:
    """Add a calendar region via wwv_flow_imp_page.create_calendar. DEV-only.

    create_calendar is a single proc that creates BOTH the page-plug AND the
    calendar-source row (it embeds plug params like p_plug_name, p_plug_template
    along with calendar params like p_start_date, p_display_as).

    APEX 24.2 ALL_ARGUMENTS: 123 params, all defaulted.

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

    sql_escaped = sql_query.replace("'", "''")
    name_esc = name.replace("'", "''")
    date_col_esc = date_column.replace("'", "''")

    plsql_body = f"""  wwv_flow_imp_page.create_calendar(
    p_id => {region_id},
    p_flow_id => {app_id},
    p_page_id => {page_id},
    p_plug_name => '{name_esc}',
    p_plug_template => {template_id},
    p_plug_display_sequence => '{display_sequence}',
    p_query_type => 'SQL',
    p_plug_source => '{sql_escaped}',
    p_start_date => '{date_col_esc}',
    p_display_as => 'NATIVE_CALENDAR'
  );
"""

    decision = enforce_policy(
        PolicyContext(
            profile=profile, tool_name="apex_add_calendar", is_destructive=False
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "region_id": region_id,
            "date_column": date_column,
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
            message=f"apex_add_calendar failed: {e}",
            suggestion="Check SQL preview via dry_run; verify sql_query/date_column are valid",
        ) from e

    after, _ = query_metadata_snapshot(profile, app_id)
    ok, reason = verify_post_success(before, after, expected_delta={"regions": 1})
    if not ok:
        raise ApexBuilderError(
            code="POST_WRITE_VERIFY_FAIL",
            message=f"calendar region write completed but metadata mismatch: {reason}",
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
        "date_column": date_column,
        "name": name,
        "alias": alias,
        "before": {"pages": before.pages, "regions": before.regions, "items": before.items},
        "after": {"pages": after.pages, "regions": after.regions, "items": after.items},
        "auto_export": export_result,
    }
