"""Unit tests for tools/generators.py (Plan 2B-7).

Coverage matrix per generator:
  * NOT_CONNECTED  - raises ApexBuilderError(code='NOT_CONNECTED')
  * PROD reject    - raises ENV_GUARD_PROD_REJECTED
  * TEST dry-run   - returns dict with dry_run=True + preview
  * DEV live       - composes sub-tools (mocked) and returns created/results

For DEV-live paths each sub-tool is patched at the
`apex_builder_mcp.tools.generators` import site (lazy imports inside the
generator function pull from those modules at call time, so we patch the
target modules directly).

Generators tested:
  - apex_generate_crud           (4 tests + invalid table_name)
  - apex_generate_dashboard      (4 tests + bare-page no-options + chart-only)
  - apex_generate_login          (1 test - DEFERRED)
  - apex_generate_modal_form     (4 tests + invalid table_name)

Plus 1 GENERATOR_PARTIAL propagation test.
"""
from __future__ import annotations

from typing import Any

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.generators import (
    apex_generate_crud,
    apex_generate_dashboard,
    apex_generate_login,
    apex_generate_modal_form,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


def _setup_state(env: str = "DEV") -> None:
    profile = Profile(
        sqlcl_name="ereport_test8001",
        environment=env,
        workspace="EREPORT",
    )
    state = get_state()
    state.set_profile(profile)
    state.mark_connected()


def _stub_ok(_marker: str) -> Any:
    """Return a no-op stub function that records its call args + returns dry_run=False dict."""
    return lambda **kw: {"dry_run": False, "_stub": _marker, **kw}


# ---------------------------------------------------------------------------
# apex_generate_crud
# ---------------------------------------------------------------------------


def test_generate_crud_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_crud(
            app_id=100, table_name="EMP",
            list_page_id=9200, form_page_id=9201,
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_generate_crud_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_crud(
            app_id=100, table_name="EMP",
            list_page_id=9200, form_page_id=9201,
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_generate_crud_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_generate_crud(
        app_id=100, table_name="EMP",
        list_page_id=9200, form_page_id=9201,
    )
    assert result["dry_run"] is True
    assert result["table_name"] == "EMP"
    assert result["list_page_id"] == 9200
    assert result["form_page_id"] == 9201
    assert "EMP" in result["preview"]


def test_generate_crud_invalid_table_name_raises():
    # Note: validate_object_name runs BEFORE state check, so no profile needed.
    from apex_builder_mcp.apex_api.sql_guard import SqlGuardError

    with pytest.raises(SqlGuardError):
        apex_generate_crud(
            app_id=100, table_name="bad-table; drop table x",
            list_page_id=9200, form_page_id=9201,
        )


def test_generate_crud_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    # Patch the underlying tools at their canonical module paths.
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.apex_add_page",
        _stub_ok("page"),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.apex_add_interactive_grid",
        _stub_ok("ig"),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.apex_add_form_region",
        _stub_ok("form_region"),
    )
    result = apex_generate_crud(
        app_id=100, table_name="EMP",
        list_page_id=9200, form_page_id=9201,
        list_page_name="My List", form_page_name="My Form",
    )
    assert result["dry_run"] is False
    assert result["created"] == {
        "list_page": 9200,
        "ig_region": 9201,  # list_page_id + 1
        "form_page": 9201,
        "form_region": 9202,  # form_page_id + 1
    }
    # Sub-tool results captured
    assert result["results"]["list_page"]["_stub"] == "page"
    assert result["results"]["ig_region"]["_stub"] == "ig"
    assert result["results"]["form_region"]["_stub"] == "form_region"


def test_generate_crud_partial_failure_raises_partial(monkeypatch):
    _setup_state(env="DEV")
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.apex_add_page",
        _stub_ok("page"),
    )

    def boom(**_: Any) -> Any:
        raise ApexBuilderError(
            code="WRITE_EXEC_FAIL",
            message="simulated IG failure",
            suggestion="x",
        )

    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.apex_add_interactive_grid", boom
    )
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_crud(
            app_id=100, table_name="EMP",
            list_page_id=9210, form_page_id=9211,
        )
    err = exc_info.value
    assert err.code == "GENERATOR_PARTIAL"
    assert err.metadata["created"] == {"list_page": 9210}
    assert err.metadata["underlying_error"] == "WRITE_EXEC_FAIL"


# ---------------------------------------------------------------------------
# apex_generate_dashboard
# ---------------------------------------------------------------------------


def test_generate_dashboard_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_dashboard(app_id=100, page_id=9220)
    assert exc_info.value.code == "NOT_CONNECTED"


def test_generate_dashboard_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_dashboard(app_id=100, page_id=9220)
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_generate_dashboard_dry_run_on_test_with_both_options():
    _setup_state(env="TEST")
    result = apex_generate_dashboard(
        app_id=100,
        page_id=9220,
        name="Sales",
        kpi_query="select 1 as v from dual",
        chart_query="select x, y from t",
    )
    assert result["dry_run"] is True
    assert result["name"] == "Sales"
    assert "page" in result["steps"]
    assert "metric_cards" in result["steps"]
    assert "jet_chart" in result["steps"]


def test_generate_dashboard_dry_run_bare_page():
    _setup_state(env="TEST")
    result = apex_generate_dashboard(app_id=100, page_id=9221)
    assert result["dry_run"] is True
    assert result["steps"] == ["page"]


def test_generate_dashboard_executes_on_dev_full(monkeypatch):
    _setup_state(env="DEV")
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.apex_add_page", _stub_ok("page")
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.apex_add_metric_cards",
        _stub_ok("kpi"),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.apex_add_jet_chart",
        _stub_ok("chart"),
    )
    result = apex_generate_dashboard(
        app_id=100,
        page_id=9230,
        name="Ops",
        kpi_query="select 1 as v from dual",
        chart_query="select x, y from t",
    )
    assert result["dry_run"] is False
    assert result["created"] == {
        "page": 9230,
        "kpi_region": 9231,
        "chart_region": 9232,
    }
    assert "kpi_region" in result["results"]
    assert "chart_region" in result["results"]


def test_generate_dashboard_executes_on_dev_chart_only(monkeypatch):
    _setup_state(env="DEV")
    page_called = {"n": 0}
    kpi_called = {"n": 0}
    chart_called = {"n": 0}

    def page_stub(**kw: Any) -> Any:
        page_called["n"] += 1
        return {"dry_run": False, **kw}

    def kpi_stub(**kw: Any) -> Any:
        kpi_called["n"] += 1
        return {"dry_run": False, **kw}

    def chart_stub(**kw: Any) -> Any:
        chart_called["n"] += 1
        return {"dry_run": False, **kw}

    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.apex_add_page", page_stub
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.apex_add_metric_cards",
        kpi_stub,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.apex_add_jet_chart",
        chart_stub,
    )
    result = apex_generate_dashboard(
        app_id=100,
        page_id=9240,
        chart_query="select x, y from t",
        # no kpi_query
    )
    assert result["dry_run"] is False
    assert "page" in result["created"]
    assert "chart_region" in result["created"]
    assert "kpi_region" not in result["created"]
    assert page_called["n"] == 1
    assert kpi_called["n"] == 0
    assert chart_called["n"] == 1


# ---------------------------------------------------------------------------
# apex_generate_login (DEFERRED)
# ---------------------------------------------------------------------------


def test_generate_login_is_deferred():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_login(app_id=100)
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_generate_login_deferred_even_without_profile():
    # Deferral is a static decision; no profile needed.
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_login(app_id=100)
    assert exc_info.value.code == "TOOL_DEFERRED"


# ---------------------------------------------------------------------------
# apex_generate_modal_form
# ---------------------------------------------------------------------------


def test_generate_modal_form_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_modal_form(app_id=100, page_id=9250, table_name="EMP")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_generate_modal_form_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_generate_modal_form(app_id=100, page_id=9250, table_name="EMP")
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_generate_modal_form_invalid_table_name_raises():
    from apex_builder_mcp.apex_api.sql_guard import SqlGuardError

    with pytest.raises(SqlGuardError):
        apex_generate_modal_form(
            app_id=100, page_id=9250, table_name="bad name; drop"
        )


def test_generate_modal_form_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_generate_modal_form(
        app_id=100, page_id=9250, table_name="EMP", name="Edit Employee"
    )
    assert result["dry_run"] is True
    assert result["table_name"] == "EMP"
    assert result["name"] == "Edit Employee"
    assert "MODAL" in result["preview"]


def test_generate_modal_form_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    captured: dict[str, Any] = {}

    def page_stub(**kw: Any) -> Any:
        captured["page_kw"] = kw
        return {"dry_run": False, **kw}

    def form_region_stub(**kw: Any) -> Any:
        captured["form_kw"] = kw
        return {"dry_run": False, **kw}

    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.apex_add_page", page_stub
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.region_types.apex_add_form_region", form_region_stub
    )
    result = apex_generate_modal_form(
        app_id=100, page_id=9260, table_name="EMP"
    )
    assert result["dry_run"] is False
    assert result["page_mode"] == "MODAL"
    assert result["created"] == {"page": 9260, "form_region": 9261}
    # Verify modal page_mode is propagated to apex_add_page
    assert captured["page_kw"]["page_mode"] == "MODAL"
    assert captured["form_kw"]["table_name"] == "EMP"
    assert captured["form_kw"]["region_id"] == 9261
