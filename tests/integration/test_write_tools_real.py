"""Integration tests for write tools on DB DEV.

These tests verify the write tools (apex_add_page/region/item) work end-to-end
with the actual import_begin/end pattern proven in Phase 0 Gate 5.

CURRENT STATUS: tests verify dry-run paths (TEST env) only. Full live DEV
write requires oracledb password auth (for read queries: workspace_id lookup,
metadata snapshot) which is NOT in Plan 2A scope. The SQLcl-subprocess-only
auth path will be added in a follow-up task — see Plan 2A T16 docstring for
details.

For now, the Phase 0 round_trip_proof.py script (scripts/round_trip_proof.py)
serves as the live integration verification — it exercises the same APEX
internal API patterns these tools use.
"""
from __future__ import annotations

import os

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.items import apex_add_item
from apex_builder_mcp.tools.pages import apex_add_page
from apex_builder_mcp.tools.regions import apex_add_region

pytestmark = pytest.mark.integration


@pytest.fixture
def test_env_state():
    """Set up TEST profile state for dry-run verification."""
    sqlcl_name = os.environ.get("APEX_TEST_SQLCL_NAME")
    if not sqlcl_name:
        pytest.skip("APEX_TEST_SQLCL_NAME not set")
    reset_state_for_tests()
    state = get_state()
    state.set_profile(
        Profile(
            sqlcl_name=sqlcl_name,
            environment="TEST",
            workspace=os.environ.get("APEX_TEST_WORKSPACE", "EREPORT"),
            auth_mode="sqlcl",
        )
    )
    state.mark_connected()
    yield
    reset_state_for_tests()


def test_add_page_dry_run_via_real_state(test_env_state):
    """TEST env returns dry-run preview without executing."""
    result = apex_add_page(
        app_id=100, page_id=8000, name="ITEST_PROBE",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page" in result["sql_preview"]


def test_add_region_dry_run_via_real_state(test_env_state):
    result = apex_add_region(
        app_id=100, page_id=8000, region_id=8100, name="ITEST_REGION",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_plug" in result["sql_preview"]


def test_add_item_dry_run_via_real_state(test_env_state):
    result = apex_add_item(
        app_id=100, page_id=8000, item_id=8200, region_id=8100, name="P8000_ITEM",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_item" in result["sql_preview"]


@pytest.mark.skip(
    reason="Live DEV write requires oracledb pool for read queries (workspace_id, metadata). "
    "Plan 2A T16 documents this gap; resolution = future task wiring SQLcl-subprocess-only "
    "fallback for read queries OR oracledb password auth setup. "
    "Phase 0 round_trip_proof.py covers the same API path with SQLcl subprocess only."
)
def test_add_page_dev_live_full_cycle():
    """[SKIPPED for MVP] Live DEV write + cleanup. See docstring above."""
