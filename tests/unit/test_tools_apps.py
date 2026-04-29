"""Unit tests for Plan 2B-8 app lifecycle tools."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.apps import (
    apex_create_app,
    apex_delete_app,
    apex_get_app_details,
    apex_validate_app,
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
# apex_get_app_details
# ---------------------------------------------------------------------------


def test_get_app_details_found(monkeypatch):
    _setup_state()
    fake_details = {
        "APPLICATION_ID": 100,
        "APPLICATION_NAME": "MY APP",
        "ALIAS": "MYAPP",
        "PAGES": 12,
        "OWNER": "EREPORT",
        "WORKSPACE": "EREPORT",
        "VERSION": "1.0",
    }
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_app_details",
        lambda profile, app_id: dict(fake_details),
    )

    result = apex_get_app_details(app_id=100)
    assert result["found"] is True
    assert result["application_id"] == 100
    assert result["details"]["APPLICATION_NAME"] == "MY APP"
    assert result["details"]["PAGES"] == 12


def test_get_app_details_not_found(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_app_details",
        lambda profile, app_id: None,
    )

    result = apex_get_app_details(app_id=99999)
    assert result["found"] is False


def test_get_app_details_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_get_app_details(app_id=100)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_validate_app
# ---------------------------------------------------------------------------


def test_validate_app_not_found(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_validate_app",
        lambda profile, app_id: None,
    )

    result = apex_validate_app(app_id=99999)
    assert result["ok"] is False
    assert any(i["code"] == "APP_NOT_FOUND" for i in result["issues"])


def test_validate_app_clean(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_validate_app",
        lambda profile, app_id: {
            "app_meta": ("MY APP", 5),
            "present_required": {0, 1},
            "orphans": [],
            "empty_pages": [],
        },
    )

    result = apex_validate_app(app_id=100)
    assert result["ok"] is True
    assert result["issues"] == []
    assert result["counts"]["orphan_items"] == 0


def test_validate_app_with_issues(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_validate_app",
        lambda profile, app_id: {
            "app_meta": ("BROKEN APP", 3),
            "present_required": {0},  # missing page 1
            "orphans": [(50, "P10_X", 10, 999)],
            "empty_pages": [(2, "Empty Page")],
        },
    )

    result = apex_validate_app(app_id=100)
    assert result["ok"] is False
    codes = {i["code"] for i in result["issues"]}
    assert "MISSING_REQUIRED_PAGE" in codes
    assert "ORPHAN_ITEM" in codes
    assert "PAGE_NO_REGIONS" in codes
    assert result["counts"]["orphan_items"] == 1
    assert result["counts"]["pages_without_regions"] == 1


def test_validate_app_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_validate_app(app_id=100)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_delete_app
# ---------------------------------------------------------------------------


def test_delete_app_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_app(app_id=100)
    assert exc_info.value.code == "NOT_CONNECTED"


def test_delete_app_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_app(app_id=100)
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_delete_app_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_delete_app(app_id=999100)
    assert result["dry_run"] is True
    assert "wwv_flow_imp.remove_flow" in result["sql_preview"]
    assert "p_id => 999100" in result["sql_preview"]


def test_delete_app_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")

    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_workspace_id",
        lambda profile, ws: 100002,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps._verify_app_gone",
        lambda profile, app_id: True,
    )

    result = apex_delete_app(app_id=999100)
    assert result["dry_run"] is False
    assert result["deleted"] is True
    assert result["app_id"] == 999100
    fake_sess.execute.assert_called_once()


def test_delete_app_post_verify_fail_when_app_still_present(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_workspace_id",
        lambda profile, ws: 100002,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps._verify_app_gone",
        lambda profile, app_id: False,
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_delete_app(app_id=999100)
    assert exc_info.value.code == "POST_WRITE_VERIFY_FAIL"


# ---------------------------------------------------------------------------
# apex_create_app
# ---------------------------------------------------------------------------


def test_create_app_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_create_app(name="Test", alias="TST")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_create_app_invalid_name():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_create_app(name="", alias="TST")
    assert exc_info.value.code == "INVALID_NAME"


def test_create_app_invalid_alias():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_create_app(name="My App", alias="bad alias!")
    assert exc_info.value.code == "INVALID_ALIAS"


def test_create_app_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_create_app(name="MyApp", alias="MYAPP", app_id=999100)
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_create_app_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_create_app(
        name="My App", alias="MYAPP", app_id=999100
    )
    assert result["dry_run"] is True
    assert result["app_id"] == 999100
    assert "wwv_flow_imp.create_flow" in result["sql_preview"]
    assert "p_alias => 'MYAPP'" in result["sql_preview"]
    assert "wwv_flow_imp_page.create_page" in result["sql_preview"]


def test_create_app_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_workspace_id",
        lambda profile, ws: 100002,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps._verify_app_exists",
        lambda profile, app_id: (True, 1),
    )

    result = apex_create_app(name="My App", alias="MYAPP", app_id=999100)
    assert result["dry_run"] is False
    assert result["app_id"] == 999100
    assert result["page_count"] == 1
    assert result["partial_functionality"] is True
    assert "caveat" in result
    fake_sess.execute.assert_called_once()


def test_create_app_post_verify_fail_when_missing(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.ImportSession", lambda **kw: fake_sess
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps.query_workspace_id",
        lambda profile, ws: 100002,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps._verify_app_exists",
        lambda profile, app_id: (False, 0),
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_create_app(name="My App", alias="MYAPP", app_id=999100)
    assert exc_info.value.code == "POST_WRITE_VERIFY_FAIL"


def test_create_app_allocates_id_when_not_given(monkeypatch):
    _setup_state(env="TEST")  # dry-run path
    monkeypatch.setattr(
        "apex_builder_mcp.tools.apps._allocate_create_app_id",
        lambda profile, ws: 999500,
    )
    result = apex_create_app(name="My App", alias="MYAPP")
    assert result["dry_run"] is True
    assert result["app_id"] == 999500
