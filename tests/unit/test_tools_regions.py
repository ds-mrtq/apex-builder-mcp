from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.regions import apex_add_region


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


def test_add_region_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_region(
            app_id=100, page_id=8000, region_id=8100, name="MyRegion"
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_region_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_region(
            app_id=100, page_id=8000, region_id=8100, name="MyRegion"
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_region_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_region(
        app_id=100, page_id=8000, region_id=8100, name="MyRegion"
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_plug" in result["sql_preview"]


def test_add_region_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.regions.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.regions.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=67, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.regions.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.regions.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_add_region(
        app_id=100, page_id=8000, region_id=8100, name="MyRegion"
    )
    assert result["dry_run"] is False
    assert result["region_id"] == 8100
    assert result["after"]["regions"] == 67
    fake_sess.execute.assert_called_once()


def test_add_region_post_success_verify_fail(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.regions.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.regions.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.regions.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_region(
            app_id=100, page_id=8000, region_id=8100, name="MyRegion"
        )
    assert exc_info.value.code == "POST_WRITE_VERIFY_FAIL"
