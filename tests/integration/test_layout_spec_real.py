"""Integration test for apex_apply_layout_spec bridge."""
from __future__ import annotations

import os

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.layout_spec import apex_apply_layout_spec

pytestmark = pytest.mark.integration


@pytest.fixture
def test_env_state():
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


def test_layout_spec_dry_run(test_env_state):
    """TEST env: layout spec expansion returns dry-run results for each region/item."""
    spec = {
        "app_id": 100,
        "page_id": 8000,
        "regions": [
            {
                "name": "demo_region",
                "template": "t-Region",
                "grid": {"col_span": 12},
                "items": [
                    {"name": "P8000_X", "type": "TEXT"},
                    {"name": "P8000_Y", "type": "DATE"},
                ],
            },
        ],
    }
    result = apex_apply_layout_spec(spec)
    assert result["regions_added"] == 1
    assert result["items_added"] == 2
    # Each child call should also be dry_run on TEST env
    assert result["regions"][0]["dry_run"] is True
    assert result["items"][0]["dry_run"] is True


@pytest.mark.skip(reason="Live DEV apply requires oracledb pool — see test_write_tools_real.py")
def test_layout_spec_dev_live():
    """[SKIPPED for MVP] Full DEV apply with probe cleanup."""
