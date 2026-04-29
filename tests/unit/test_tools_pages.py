from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.pages import apex_add_page


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


def test_add_page_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_page(app_id=100, page_id=8000, name="Test")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_page_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_page(app_id=100, page_id=8000, name="Test")
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_page_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_page(app_id=100, page_id=8000, name="Test")
    assert result["dry_run"] is True
    assert "wwv_flow_imp_page.create_page" in result["sql_preview"]


def test_add_page_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")

    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.ImportSession", lambda **kw: fake_sess
    )

    fake_cur = MagicMock()
    # Order of fetchone calls: workspace_id, before snapshot, after snapshot
    fake_cur.fetchone.side_effect = [
        (100002,),
        (25, 66, 41, "DATA-LOADING"),
        (26, 66, 41, "DATA-LOADING"),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages._get_pool", lambda: fake_pool
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.refresh_export",
        lambda **kw: {"skipped": True},
    )

    result = apex_add_page(app_id=100, page_id=8000, name="Probe")
    assert result["dry_run"] is False
    assert result["app_id"] == 100
    assert result["page_id"] == 8000
    assert result["after"]["pages"] == 26
    fake_sess.execute.assert_called_once()


def test_add_page_post_success_verify_fail(monkeypatch):
    """If metadata didn't actually change after import session, raise verify fail."""
    _setup_state(env="DEV")

    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages.ImportSession", lambda **kw: fake_sess
    )

    fake_cur = MagicMock()
    fake_cur.fetchone.side_effect = [
        (100002,),
        (25, 66, 41, "DATA-LOADING"),
        (25, 66, 41, "DATA-LOADING"),  # didn't change!
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages._get_pool", lambda: fake_pool
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_page(app_id=100, page_id=8000, name="Probe")
    assert exc_info.value.code == "POST_WRITE_VERIFY_FAIL"


def test_add_page_app_not_found_raises(monkeypatch):
    _setup_state(env="DEV")

    fake_cur = MagicMock()
    fake_cur.fetchone.side_effect = [(100002,), None]  # workspace_id ok, but app not found
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.pages._get_pool", lambda: fake_pool
    )

    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_page(app_id=999, page_id=8000, name="Probe")
    assert exc_info.value.code == "APP_NOT_FOUND"
