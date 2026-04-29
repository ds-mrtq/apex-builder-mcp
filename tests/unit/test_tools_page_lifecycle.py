from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.page_lifecycle import (
    apex_delete_page,
    apex_update_page,
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
# apex_delete_page
# ---------------------------------------------------------------------------


def test_delete_page_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_page(app_id=100, page_id=8500)
    assert exc_info.value.code == "NOT_CONNECTED"


def test_delete_page_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_page(app_id=100, page_id=8500)
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_delete_page_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_delete_page(app_id=100, page_id=8500)
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.remove_page" in result["sql_preview"]
    assert "p_flow_id => 100" in result["sql_preview"]
    assert "p_page_id => 8500" in result["sql_preview"]


def test_delete_page_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")

    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.query_workspace_id",
        lambda profile, ws: 100002,
    )
    snaps = iter(
        [
            (MetadataSnapshot(pages=26, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.query_metadata_snapshot",
        lambda profile, app_id: next(snaps),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_delete_page(app_id=100, page_id=8500)
    assert result["dry_run"] is False
    assert result["app_id"] == 100
    assert result["page_id"] == 8500
    assert result["before"]["pages"] == 26
    assert result["after"]["pages"] == 25
    fake_sess.execute.assert_called_once()


def test_delete_page_post_verify_fail_when_no_change(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.query_workspace_id",
        lambda profile, ws: 100002,
    )
    snaps = iter(
        [
            (MetadataSnapshot(pages=26, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=26, regions=66, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.query_metadata_snapshot",
        lambda profile, app_id: next(snaps),
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_page(app_id=100, page_id=8500)
    assert exc_info.value.code == "POST_WRITE_VERIFY_FAIL"


# ---------------------------------------------------------------------------
# apex_update_page
# ---------------------------------------------------------------------------


def test_update_page_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_update_page(app_id=100, page_id=8500, name="X")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_update_page_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_update_page(app_id=100, page_id=8500, name="X")
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_update_page_no_fields_raises():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_update_page(app_id=100, page_id=8500)
    assert exc_info.value.code == "UPDATE_NO_FIELDS"


def test_update_page_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_update_page(app_id=100, page_id=8500, name="Renamed")
    assert result["dry_run"] is True
    assert "wwv_flow_imp.update_page" in result["sql_preview"]
    assert "p_name => 'Renamed'" in result["sql_preview"]


def test_update_page_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.query_workspace_id",
        lambda profile, ws: 100002,
    )
    snap = MetadataSnapshot(pages=26, regions=66, items=41)
    snaps = iter([(snap, "DATA-LOADING"), (snap, "DATA-LOADING")])
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.query_metadata_snapshot",
        lambda profile, app_id: next(snaps),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_lifecycle.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_update_page(
        app_id=100, page_id=8500, name="Renamed", step_title="New Title"
    )
    assert result["dry_run"] is False
    # No count delta expected for update
    assert result["after"]["pages"] == 26
    fake_sess.execute.assert_called_once()
