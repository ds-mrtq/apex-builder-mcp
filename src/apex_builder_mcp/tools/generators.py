"""High-level generator tools for Plan 2B-7.

Generators COMPOSE existing low-level write tools (apex_add_page,
apex_add_interactive_grid, apex_add_form_region, apex_add_metric_cards,
apex_add_jet_chart) into common APEX patterns. Each generator wraps the
sequential calls into a single best-effort atomic operation.

Atomicity caveat
----------------
APEX `wwv_flow_imp.*` procs auto-commit per ImportSession (each low-level
tool opens its own session). True atomicity across multiple sessions is
not possible without a single-session compositor, which is out of scope
for MVP. If a step fails after others have succeeded, the partial state
is left as-is and the generator raises ApexBuilderError(code='GENERATOR_PARTIAL')
with `metadata.created` listing what was created so far. Callers must
manually clean up via apex_delete_page (or similar).

Implemented
-----------
1. apex_generate_crud(app_id, table_name, list_page_id, form_page_id, ...)
   - List page (Interactive Grid over the table)
   - Form page (NATIVE_FORM bound to the table)

2. apex_generate_dashboard(app_id, page_id, name='Dashboard',
                           kpi_query=None, chart_query=None)
   - Page + optional metric_cards region (kpi) + optional jet_chart region

3. apex_generate_modal_form(app_id, page_id, table_name, name=None)
   - Page with page_mode='MODAL' + NATIVE_FORM region bound to table

Deferred
--------
4. apex_generate_login -> TOOL_DEFERRED
   APEX 24.2 default Custom Authentication includes a built-in login page
   wired to the APEX_AUTHENTICATION schema; minimum required to reproduce
   it via wwv_flow_imp_page.create_page would mean seeding the
   USERNAME/PASSWORD items, the Login button, the
   apex_authentication.login process, plus authentication scheme wiring.
   That surface is impractical for a generator MVP. Use the App Builder
   "Create > Login Page" wizard instead. See suggestion in raised error.
"""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.apex_api.sql_guard import validate_object_name
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.guard.policy import PolicyContext, enforce_policy
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile


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
# 1. apex_generate_crud
# ---------------------------------------------------------------------------


@apex_tool(name="apex_generate_crud", category=Category.WRITE_CORE)
def apex_generate_crud(
    app_id: int,
    table_name: str,
    list_page_id: int,
    form_page_id: int,
    list_page_name: str | None = None,
    form_page_name: str | None = None,
) -> dict[str, Any]:
    """Generate full CRUD for a table: list page (IG) + form page (NATIVE_FORM).

    Composes 4 low-level calls in sequence:
      1. apex_add_page(list_page_id)
      2. apex_add_interactive_grid(list_page_id, region_id=list_page_id+1)
      3. apex_add_page(form_page_id)
      4. apex_add_form_region(form_page_id, region_id=form_page_id+1)

    NOT atomic across calls — each underlying tool opens its own ImportSession
    which auto-commits. On mid-way failure, raises GENERATOR_PARTIAL with
    `metadata.created` listing artifacts that succeeded.

    Returns a dict with `created` mapping each artifact role to its id, plus
    the full sub-tool results in `results` for caller introspection.
    """
    validate_object_name(table_name, raise_on_fail=True)
    profile = _require_profile()

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_generate_crud",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "table_name": table_name,
            "list_page_id": list_page_id,
            "form_page_id": form_page_id,
            "preview": (
                f"Would create list page {list_page_id} with IG over {table_name}, "
                f"form page {form_page_id} with NATIVE_FORM bound to {table_name}."
            ),
        }

    # Lazy import sub-tools to avoid registry cycles at module import time
    from apex_builder_mcp.tools.pages import apex_add_page
    from apex_builder_mcp.tools.region_types import (
        apex_add_form_region,
        apex_add_interactive_grid,
    )

    created: dict[str, int] = {}
    results: dict[str, Any] = {}

    try:
        list_result = apex_add_page(
            app_id=app_id,
            page_id=list_page_id,
            name=list_page_name or f"List {table_name}",
        )
        created["list_page"] = list_page_id
        results["list_page"] = list_result

        ig_region_id = list_page_id + 1
        ig_result = apex_add_interactive_grid(
            app_id=app_id,
            page_id=list_page_id,
            region_id=ig_region_id,
            sql_query=f"select * from {table_name}",
            name=f"{table_name} Grid",
        )
        created["ig_region"] = ig_region_id
        results["ig_region"] = ig_result

        form_result = apex_add_page(
            app_id=app_id,
            page_id=form_page_id,
            name=form_page_name or f"Edit {table_name}",
        )
        created["form_page"] = form_page_id
        results["form_page"] = form_result

        form_region_id = form_page_id + 1
        form_region_result = apex_add_form_region(
            app_id=app_id,
            page_id=form_page_id,
            region_id=form_region_id,
            table_name=table_name,
            name=f"{table_name} Form",
        )
        created["form_region"] = form_region_id
        results["form_region"] = form_region_result
    except ApexBuilderError as e:
        raise ApexBuilderError(
            code="GENERATOR_PARTIAL",
            message=f"apex_generate_crud failed mid-way: {e.message}",
            suggestion=(
                f"Created so far: {created}. Manually clean up via apex_delete_page "
                f"for each created page id."
            ),
            metadata={"created": created, "underlying_error": e.code},
        ) from e

    return {
        "dry_run": False,
        "app_id": app_id,
        "table_name": table_name,
        "created": created,
        "results": results,
    }


# ---------------------------------------------------------------------------
# 2. apex_generate_dashboard
# ---------------------------------------------------------------------------


@apex_tool(name="apex_generate_dashboard", category=Category.WRITE_CORE)
def apex_generate_dashboard(
    app_id: int,
    page_id: int,
    name: str = "Dashboard",
    kpi_query: str | None = None,
    chart_query: str | None = None,
) -> dict[str, Any]:
    """Generate a dashboard page with optional KPI cards and chart.

    Composes 1-3 low-level calls:
      1. apex_add_page(page_id, name)
      2. apex_add_metric_cards(...) if kpi_query provided
      3. apex_add_jet_chart(...) if chart_query provided

    Region ids are derived: kpi uses page_id+1, chart uses page_id+2 (so a
    bare page reserves a 3-id span). If neither kpi_query nor chart_query
    is provided, the result is just the bare page (still useful as a
    container).

    NOT atomic across calls; raises GENERATOR_PARTIAL on mid-way failure.
    """
    profile = _require_profile()

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_generate_dashboard",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        steps = ["page"]
        if kpi_query is not None:
            steps.append("metric_cards")
        if chart_query is not None:
            steps.append("jet_chart")
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "name": name,
            "steps": steps,
            "preview": (
                f"Would create page {page_id} '{name}'"
                + (
                    f" + metric_cards (region {page_id + 1}) over kpi_query"
                    if kpi_query is not None
                    else ""
                )
                + (
                    f" + jet_chart (region {page_id + 2}) over chart_query"
                    if chart_query is not None
                    else ""
                )
            ),
        }

    from apex_builder_mcp.tools.charts_cards_calendar import (
        apex_add_jet_chart,
        apex_add_metric_cards,
    )
    from apex_builder_mcp.tools.pages import apex_add_page

    created: dict[str, int] = {}
    results: dict[str, Any] = {}

    try:
        page_result = apex_add_page(app_id=app_id, page_id=page_id, name=name)
        created["page"] = page_id
        results["page"] = page_result

        if kpi_query is not None:
            kpi_region_id = page_id + 1
            kpi_result = apex_add_metric_cards(
                app_id=app_id,
                page_id=page_id,
                region_id=kpi_region_id,
                sql_query=kpi_query,
                name=f"{name} KPI",
            )
            created["kpi_region"] = kpi_region_id
            results["kpi_region"] = kpi_result

        if chart_query is not None:
            chart_region_id = page_id + 2
            chart_result = apex_add_jet_chart(
                app_id=app_id,
                page_id=page_id,
                region_id=chart_region_id,
                sql_query=chart_query,
                name=f"{name} Chart",
            )
            created["chart_region"] = chart_region_id
            results["chart_region"] = chart_result
    except ApexBuilderError as e:
        raise ApexBuilderError(
            code="GENERATOR_PARTIAL",
            message=f"apex_generate_dashboard failed mid-way: {e.message}",
            suggestion=(
                f"Created so far: {created}. Manually clean up via apex_delete_page."
            ),
            metadata={"created": created, "underlying_error": e.code},
        ) from e

    return {
        "dry_run": False,
        "app_id": app_id,
        "page_id": page_id,
        "name": name,
        "created": created,
        "results": results,
    }


# ---------------------------------------------------------------------------
# 3. apex_generate_login (DEFERRED)
# ---------------------------------------------------------------------------


@apex_tool(name="apex_generate_login", category=Category.WRITE_CORE)
def apex_generate_login(
    app_id: int,
    page_id: int = 101,
    name: str = "Login",
) -> dict[str, Any]:
    """[DEFERRED for MVP] Generate a standard APEX login page.

    APEX 24.2 ships a default Custom Authentication login page (page 9999 in
    the Application Express runtime, or a user-created copy via the
    'Create > Login Page' wizard in App Builder). Reproducing that wizard
    via wwv_flow_imp.* procs requires:

      1. wwv_flow_imp_page.create_page (with p_page_function='LOGIN' or
         similar mode)
      2. wwv_flow_imp_page.create_page_item for P101_USERNAME / P101_PASSWORD
         (correct attributes for password masking + auto-complete)
      3. wwv_flow_imp_page.create_page_button for the Login button
      4. wwv_flow_imp_page.create_page_process for the
         apex_authentication.login(p_username => :P101_USERNAME,
         p_password => :P101_PASSWORD) call (must run on submit)
      5. Authentication scheme wiring at the app level

    Each of those is its own MVP-deferred tool surface. Until the
    underlying surfaces stabilize (notably p_page_function='LOGIN' is not
    documented as a public knob), this generator is deferred to Phase 3.

    Workaround: Use App Builder "Create > Login Page" wizard, which ships
    the canonical login page in 1 click.
    """
    raise ApexBuilderError(
        code="TOOL_DEFERRED",
        message="apex_generate_login not implemented in MVP",
        suggestion=(
            "Use App Builder 'Create > Login Page' wizard which ships the "
            "canonical login page in one click. APEX's default Custom "
            "Authentication wires a built-in login flow that's impractical "
            "to reproduce via wwv_flow_imp procs in MVP. Deferred to Phase 3."
        ),
        metadata={
            "app_id": app_id,
            "page_id": page_id,
            "name": name,
        },
    )


# ---------------------------------------------------------------------------
# 4. apex_generate_modal_form
# ---------------------------------------------------------------------------


@apex_tool(name="apex_generate_modal_form", category=Category.WRITE_CORE)
def apex_generate_modal_form(
    app_id: int,
    page_id: int,
    table_name: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Generate a modal form page (page_mode='MODAL') with NATIVE_FORM region.

    Composes 2 low-level calls:
      1. apex_add_page(page_id, page_mode='MODAL')
      2. apex_add_form_region(region_id=page_id+1, table_name)

    NOT atomic across calls; raises GENERATOR_PARTIAL on mid-way failure.
    """
    validate_object_name(table_name, raise_on_fail=True)
    profile = _require_profile()

    page_name = name or f"Edit {table_name}"

    decision = enforce_policy(
        PolicyContext(
            profile=profile,
            tool_name="apex_generate_modal_form",
            is_destructive=False,
        )
    )
    if not decision.proceed_live:
        return {
            "dry_run": True,
            "app_id": app_id,
            "page_id": page_id,
            "table_name": table_name,
            "name": page_name,
            "preview": (
                f"Would create modal page {page_id} (page_mode='MODAL') with "
                f"NATIVE_FORM region (id {page_id + 1}) bound to {table_name}."
            ),
        }

    from apex_builder_mcp.tools.pages import apex_add_page
    from apex_builder_mcp.tools.region_types import apex_add_form_region

    created: dict[str, int] = {}
    results: dict[str, Any] = {}

    try:
        page_result = apex_add_page(
            app_id=app_id,
            page_id=page_id,
            name=page_name,
            page_mode="MODAL",
        )
        created["page"] = page_id
        results["page"] = page_result

        form_region_id = page_id + 1
        form_result = apex_add_form_region(
            app_id=app_id,
            page_id=page_id,
            region_id=form_region_id,
            table_name=table_name,
            name=f"{table_name} Form",
        )
        created["form_region"] = form_region_id
        results["form_region"] = form_result
    except ApexBuilderError as e:
        raise ApexBuilderError(
            code="GENERATOR_PARTIAL",
            message=f"apex_generate_modal_form failed mid-way: {e.message}",
            suggestion=(
                f"Created so far: {created}. Manually clean up via apex_delete_page."
            ),
            metadata={"created": created, "underlying_error": e.code},
        ) from e

    return {
        "dry_run": False,
        "app_id": app_id,
        "page_id": page_id,
        "table_name": table_name,
        "name": page_name,
        "page_mode": "MODAL",
        "created": created,
        "results": results,
    }
