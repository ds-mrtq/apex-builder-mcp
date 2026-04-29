from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.item_lifecycle import (
    apex_delete_item,
    apex_update_item,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


def _setup_state(env: str = "DEV") -> None:
    profile = Profile(
        sqlcl_name="ereport_test8001",
        environment=env,  # type: ignore[arg-type]
        workspace="EREPORT",
    )
    state = get_state()
    state.set_profile(profile)
    state.mark_connected()


# ---------------------------------------------------------------------------
# apex_delete_item
# ---------------------------------------------------------------------------


def test_delete_item_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_item(app_id=100, page_id=8500, item_id=99999)
    assert exc_info.value.code == "NOT_CONNECTED"


def test_delete_item_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_item(app_id=100, page_id=8500, item_id=99999)
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_delete_item_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_delete_item(app_id=100, page_id=8500, item_id=99999)
    assert result["dry_run"] is True
    assert "wwv_flow_app_builder_api.delete_page_item" in result["sql_preview"]
    assert "p_page_id => 8500" in result["sql_preview"]
    assert "p_item_id => 99999" in result["sql_preview"]


def test_delete_item_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.query_workspace_id",
        lambda profile, ws: 100002,
    )
    snaps = iter(
        [
            (MetadataSnapshot(pages=26, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=26, regions=66, items=40), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.query_metadata_snapshot",
        lambda profile, app_id: next(snaps),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_delete_item(app_id=100, page_id=8500, item_id=99999)
    assert result["dry_run"] is False
    assert result["before"]["items"] == 41
    assert result["after"]["items"] == 40
    fake_sess.execute.assert_called_once()


# ---------------------------------------------------------------------------
# apex_update_item
# ---------------------------------------------------------------------------


def test_update_item_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_update_item(app_id=100, page_id=8500, item_id=99999, label="X")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_update_item_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_update_item(app_id=100, page_id=8500, item_id=99999, label="X")
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_update_item_no_fields_raises():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_update_item(app_id=100, page_id=8500, item_id=99999)
    assert exc_info.value.code == "UPDATE_NO_FIELDS"


def test_update_item_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_update_item(
        app_id=100, page_id=8500, item_id=99999, label="New Label"
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp.update_page_item" in result["sql_preview"]
    assert "p_new_label => 'New Label'" in result["sql_preview"]


def test_update_item_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.query_workspace_id",
        lambda profile, ws: 100002,
    )
    snap = MetadataSnapshot(pages=26, regions=66, items=41)
    snaps = iter([(snap, "DATA-LOADING"), (snap, "DATA-LOADING")])
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.query_metadata_snapshot",
        lambda profile, app_id: next(snaps),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.item_lifecycle.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_update_item(
        app_id=100,
        page_id=8500,
        item_id=99999,
        label="New Label",
        display_sequence=20,
    )
    assert result["dry_run"] is False
    assert result["after"]["items"] == 41
    fake_sess.execute.assert_called_once()
