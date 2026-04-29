"""Unit tests for tools/charts_cards_calendar.py (Plan 2B-4).

Coverage:
  * apex_add_jet_chart       - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
  * apex_add_metric_cards    - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
  * apex_add_calendar        - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.charts_cards_calendar import (
    apex_add_calendar,
    apex_add_jet_chart,
    apex_add_metric_cards,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


def _setup_state(env="DEV"):
    profile = Profile(
        sqlcl_name="ereport_test8001",
        environment=env,
        workspace="EREPORT",
    )
    state = get_state()
    state.set_profile(profile)
    state.mark_connected()


def _patch_live_path(monkeypatch):
    """Wire the standard mocks for the live (DEV) execution path."""
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=67, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.charts_cards_calendar.refresh_export",
        lambda **kw: {"skipped": True},
    )
    return fake_sess


# ---------------------------------------------------------------------------
# apex_add_jet_chart
# ---------------------------------------------------------------------------


def test_add_jet_chart_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_jet_chart(
            app_id=100, page_id=8800, region_id=8801,
            sql_query="select 1 as v from dual", name="CHART",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_jet_chart_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_jet_chart(
            app_id=100, page_id=8800, region_id=8801,
            sql_query="select 1 as v from dual", name="CHART",
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_jet_chart_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_jet_chart(
        app_id=100, page_id=8800, region_id=8801,
        sql_query="select 1 as v from dual", name="CHART",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_plug" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_jet_chart" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_jet_chart_series" in result["sql_preview"]
    assert "NATIVE_JET_CHART_V2" in result["sql_preview"]
    assert "p_chart_type => 'bar'" in result["sql_preview"]
    assert result["region_id"] == 8801
    assert result["chart_id"] == 8801
    assert result["series_id"] == 8802


def test_add_jet_chart_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch)
    result = apex_add_jet_chart(
        app_id=100, page_id=8800, region_id=8801,
        sql_query="select c, n from t", name="CHART", chart_type="pie",
    )
    assert result["dry_run"] is False
    assert result["region_id"] == 8801
    assert result["chart_type"] == "pie"
    assert result["after"]["regions"] == 67
    fake_sess.execute.assert_called_once()


# ---------------------------------------------------------------------------
# apex_add_metric_cards
# ---------------------------------------------------------------------------


def test_add_metric_cards_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_metric_cards(
            app_id=100, page_id=8800, region_id=8810,
            sql_query="select 1 as v from dual", name="CARDS",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_metric_cards_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_metric_cards(
            app_id=100, page_id=8800, region_id=8810,
            sql_query="select 1 as v from dual", name="CARDS",
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_metric_cards_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_metric_cards(
        app_id=100, page_id=8800, region_id=8810,
        sql_query="select 1 as v from dual", name="CARDS",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_plug" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_card" in result["sql_preview"]
    assert "NATIVE_CARDS" in result["sql_preview"]
    assert result["region_id"] == 8810
    assert result["card_id"] == 8810


def test_add_metric_cards_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch)
    result = apex_add_metric_cards(
        app_id=100, page_id=8800, region_id=8810,
        sql_query="select t.x as title, t.y as body from t", name="CARDS",
    )
    assert result["dry_run"] is False
    assert result["region_id"] == 8810
    assert result["after"]["regions"] == 67
    fake_sess.execute.assert_called_once()


# ---------------------------------------------------------------------------
# apex_add_calendar
# ---------------------------------------------------------------------------


def test_add_calendar_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_calendar(
            app_id=100, page_id=8800, region_id=8820,
            sql_query="select * from t", name="CAL",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_calendar_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_calendar(
            app_id=100, page_id=8800, region_id=8820,
            sql_query="select * from t", name="CAL",
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_calendar_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_calendar(
        app_id=100, page_id=8800, region_id=8820,
        sql_query="select * from t", name="CAL",
        date_column="EVENT_DATE",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_calendar" in result["sql_preview"]
    assert "p_start_date => 'EVENT_DATE'" in result["sql_preview"]
    assert "p_display_as => 'NATIVE_CALENDAR'" in result["sql_preview"]
    assert result["region_id"] == 8820
    assert result["date_column"] == "EVENT_DATE"


def test_add_calendar_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch)
    result = apex_add_calendar(
        app_id=100, page_id=8800, region_id=8820,
        sql_query="select * from t", name="CAL",
    )
    assert result["dry_run"] is False
    assert result["region_id"] == 8820
    assert result["date_column"] == "START_DATE"
    assert result["after"]["regions"] == 67
    fake_sess.execute.assert_called_once()
