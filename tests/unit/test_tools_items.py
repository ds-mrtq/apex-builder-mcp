from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.items import apex_add_item


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


def test_add_item_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_item(
            app_id=100, page_id=8000, item_id=8200,
            region_id=8100, name="P8000_X",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_item_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError):
        apex_add_item(
            app_id=100, page_id=8000, item_id=8200,
            region_id=8100, name="P8000_X",
        )


def test_add_item_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_item(
        app_id=100, page_id=8000, item_id=8200,
        region_id=8100, name="P8000_X",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_item" in result["sql_preview"]


def test_add_item_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=66, items=42), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_add_item(
        app_id=100, page_id=8000, item_id=8200,
        region_id=8100, name="P8000_X",
    )
    assert result["dry_run"] is False
    assert result["item_id"] == 8200
    assert result["after"]["items"] == 42
    fake_sess.execute.assert_called_once()
