from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.items_bulk import apex_bulk_add_items


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


def _three_items() -> list[dict[str, object]]:
    return [
        {"item_id": 8201, "name": "P8500_A"},
        {"item_id": 8202, "name": "P8500_B", "display_as": "NATIVE_TEXTAREA"},
        {"item_id": 8203, "name": "P8500_C", "display_sequence": 30},
    ]


def test_bulk_empty_raises():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_bulk_add_items(app_id=100, page_id=8500, region_id=8100, items=[])
    assert exc_info.value.code == "BULK_EMPTY"


def test_bulk_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_bulk_add_items(
            app_id=100, page_id=8500, region_id=8100, items=_three_items()
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_bulk_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_bulk_add_items(
            app_id=100, page_id=8500, region_id=8100, items=_three_items()
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_bulk_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_bulk_add_items(
        app_id=100, page_id=8500, region_id=8100, items=_three_items()
    )
    assert result["dry_run"] is True
    assert result["item_count"] == 3
    # Three create_page_item calls in body
    assert result["sql_preview"].count("wwv_flow_imp_page.create_page_item") == 3


def test_bulk_missing_field_raises():
    _setup_state(env="DEV")
    bad = [{"item_id": 8201}]  # missing 'name'
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_bulk_add_items(app_id=100, page_id=8500, region_id=8100, items=bad)
    assert exc_info.value.code == "BULK_ITEM_MISSING_FIELD"


def test_bulk_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items_bulk.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items_bulk.query_workspace_id",
        lambda profile, ws: 100002,
    )
    snaps = iter(
        [
            (MetadataSnapshot(pages=26, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=26, regions=66, items=44), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items_bulk.query_metadata_snapshot",
        lambda profile, app_id: next(snaps),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items_bulk.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_bulk_add_items(
        app_id=100, page_id=8500, region_id=8100, items=_three_items()
    )
    assert result["dry_run"] is False
    assert result["item_count"] == 3
    assert result["before"]["items"] == 41
    assert result["after"]["items"] == 44
    # Single ImportSession.execute call (atomicity)
    fake_sess.execute.assert_called_once()


def test_bulk_post_verify_fail_when_partial(monkeypatch):
    """If only 2 of 3 items got created, expected_delta mismatch -> verify fail."""
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items_bulk.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items_bulk.query_workspace_id",
        lambda profile, ws: 100002,
    )
    snaps = iter(
        [
            (MetadataSnapshot(pages=26, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=26, regions=66, items=43), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.items_bulk.query_metadata_snapshot",
        lambda profile, app_id: next(snaps),
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_bulk_add_items(
            app_id=100, page_id=8500, region_id=8100, items=_three_items()
        )
    assert exc_info.value.code == "POST_WRITE_VERIFY_FAIL"
