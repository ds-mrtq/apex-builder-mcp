from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.dynamic_actions import apex_add_dynamic_action


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


def test_add_dynamic_action_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_dynamic_action(
            app_id=100,
            page_id=8000,
            da_event_id=8604,
            da_action_id=8605,
            name="DA1",
            triggering_element="#P1_X",
            event_type="click",
            action_type="NATIVE_ALERT",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_dynamic_action_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_dynamic_action(
            app_id=100,
            page_id=8000,
            da_event_id=8604,
            da_action_id=8605,
            name="DA1",
            triggering_element="#P1_X",
            event_type="click",
            action_type="NATIVE_ALERT",
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_dynamic_action_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_dynamic_action(
        app_id=100,
        page_id=8000,
        da_event_id=8604,
        da_action_id=8605,
        name="DA1",
        triggering_element="#P1_X",
        event_type="click",
        action_type="NATIVE_ALERT",
        action_attribute_01="hello",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page_da_event" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_page_da_action" in result["sql_preview"]
    assert result["da_event_id"] == 8604
    assert result["da_action_id"] == 8605


def test_add_dynamic_action_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")

    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions._verify_da_exists",
        lambda profile, app_id, page_id, da_event_id: True,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_add_dynamic_action(
        app_id=100,
        page_id=8000,
        da_event_id=8604,
        da_action_id=8605,
        name="DA1",
        triggering_element="#P1_X",
        event_type="click",
        action_type="NATIVE_ALERT",
    )
    assert result["dry_run"] is False
    assert result["da_event_id"] == 8604
    assert result["da_action_id"] == 8605
    # Single ImportSession.execute call carrying both internal create_* invocations.
    fake_sess.execute.assert_called_once()


def test_add_dynamic_action_post_verify_fail(monkeypatch):
    _setup_state(env="DEV")

    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions.query_metadata_snapshot",
        lambda profile, app_id: (
            MetadataSnapshot(pages=25, regions=66, items=41),
            "DATA-LOADING",
        ),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.dynamic_actions._verify_da_exists",
        lambda profile, app_id, page_id, da_event_id: False,
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_dynamic_action(
            app_id=100,
            page_id=8000,
            da_event_id=8604,
            da_action_id=8605,
            name="DA1",
            triggering_element="#P1_X",
            event_type="click",
            action_type="NATIVE_ALERT",
        )
    assert exc_info.value.code == "POST_WRITE_VERIFY_FAIL"
