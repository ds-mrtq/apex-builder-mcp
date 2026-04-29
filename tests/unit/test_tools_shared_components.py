"""Unit tests for tools/shared_components.py (Plan 2B-5).

Coverage:
  * apex_add_lov            - 5 tests (NOT_CONNECTED, PROD, TEST, DEV static, INVALID_PARAM)
  * apex_list_lovs          - 1 test  (read mock)
  * apex_add_auth_scheme    - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
  * apex_add_nav_item       - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
  * apex_add_app_item       - 4 tests (NOT_CONNECTED, PROD, TEST, DEV)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.shared_components import (
    apex_add_app_item,
    apex_add_auth_scheme,
    apex_add_lov,
    apex_add_nav_item,
    apex_list_lovs,
)


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


def _patch_live_path(monkeypatch, verify_helper_name: str):
    """Wire the standard mocks for the live (DEV) execution path.

    verify_helper_name is one of the _verify_*_exists symbols in
    shared_components; we monkeypatch it to True so post-write verify passes.
    """
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.shared_components.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.shared_components.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.shared_components.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.shared_components.refresh_export",
        lambda **kw: {"skipped": True},
    )
    monkeypatch.setattr(
        f"apex_builder_mcp.tools.shared_components.{verify_helper_name}",
        lambda *a, **k: True,
    )
    return fake_sess


# ---------------------------------------------------------------------------
# apex_add_lov
# ---------------------------------------------------------------------------


def test_add_lov_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_lov(app_id=100, lov_id=8901, name="STATUS_LOV")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_lov_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_lov(app_id=100, lov_id=8901, name="STATUS_LOV")
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_lov_invalid_type():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_lov(app_id=100, lov_id=8901, name="X", lov_type="GARBAGE")
    assert exc_info.value.code == "INVALID_PARAM"


def test_add_lov_dynamic_requires_sql():
    _setup_state(env="DEV")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_lov(app_id=100, lov_id=8901, name="X", lov_type="DYNAMIC")
    assert exc_info.value.code == "INVALID_PARAM"


def test_add_lov_dry_run_on_test_with_static():
    _setup_state(env="TEST")
    result = apex_add_lov(
        app_id=100, lov_id=8901, name="STATUS_LOV",
        static_values=[
            {"display": "Active", "return": "A"},
            {"display": "Inactive", "return": "I"},
        ],
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_shared.create_list_of_values" in result["sql_preview"]
    assert "wwv_flow_imp_shared.create_static_lov_data" in result["sql_preview"]
    assert "Active" in result["sql_preview"]
    assert result["lov_type"] == "STATIC"


def test_add_lov_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch, "_verify_lov_exists")
    result = apex_add_lov(
        app_id=100, lov_id=8901, name="STATUS_LOV",
        static_values=[{"display": "A", "return": "A"}],
    )
    assert result["dry_run"] is False
    assert result["lov_id"] == 8901
    assert result["static_value_count"] == 1
    fake_sess.execute.assert_called_once()


# ---------------------------------------------------------------------------
# apex_list_lovs (read)
# ---------------------------------------------------------------------------


def test_list_lovs_returns_dict(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        (1001, "STATUS_LOV", "Static"),
        (1002, "ROLE_LOV", "Dynamic"),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.shared_components._get_pool", lambda: fake_pool
    )
    result = apex_list_lovs(app_id=100)
    assert result["count"] == 2
    assert result["lovs"][0]["lov_id"] == 1001
    assert result["lovs"][0]["name"] == "STATUS_LOV"


# ---------------------------------------------------------------------------
# apex_add_auth_scheme
# ---------------------------------------------------------------------------


def test_add_auth_scheme_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_auth_scheme(app_id=100, auth_id=8910, name="MY_AUTH")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_auth_scheme_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_auth_scheme(app_id=100, auth_id=8910, name="MY_AUTH")
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_auth_scheme_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_auth_scheme(
        app_id=100, auth_id=8910, name="MY_AUTH",
        scheme_type="NATIVE_CUSTOM",
        plsql_code="return :APP_USER is not null;",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_shared.create_authentication" in result["sql_preview"]
    assert "p_scheme_type => 'NATIVE_CUSTOM'" in result["sql_preview"]
    assert "APP_USER" in result["sql_preview"]
    assert result["auth_id"] == 8910


def test_add_auth_scheme_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch, "_verify_auth_exists")
    result = apex_add_auth_scheme(
        app_id=100, auth_id=8910, name="MY_AUTH",
    )
    assert result["dry_run"] is False
    assert result["auth_id"] == 8910
    fake_sess.execute.assert_called_once()


# ---------------------------------------------------------------------------
# apex_add_nav_item
# ---------------------------------------------------------------------------


def test_add_nav_item_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_nav_item(
            app_id=100, list_item_id=8920, list_id=500,
            name="Reports", target_url="f?p=&APP_ID.:1",
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_nav_item_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_nav_item(
            app_id=100, list_item_id=8920, list_id=500,
            name="Reports", target_url="f?p=&APP_ID.:1",
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_nav_item_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_nav_item(
        app_id=100, list_item_id=8920, list_id=500,
        name="Reports", target_url="f?p=&APP_ID.:1",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_shared.create_list_item" in result["sql_preview"]
    assert "Reports" in result["sql_preview"]
    assert "p_list_id => 500" in result["sql_preview"]
    assert result["list_item_id"] == 8920


def test_add_nav_item_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch, "_verify_list_item_exists")
    result = apex_add_nav_item(
        app_id=100, list_item_id=8920, list_id=500,
        name="Reports", target_url="f?p=&APP_ID.:1",
    )
    assert result["dry_run"] is False
    assert result["list_item_id"] == 8920
    fake_sess.execute.assert_called_once()


# ---------------------------------------------------------------------------
# apex_add_app_item
# ---------------------------------------------------------------------------


def test_add_app_item_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_app_item(app_id=100, item_id=8930, name="G_USER")
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_app_item_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_app_item(app_id=100, item_id=8930, name="G_USER")
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_app_item_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_app_item(app_id=100, item_id=8930, name="G_USER")
    assert result["dry_run"] is True
    assert "wwv_flow_imp_shared.create_flow_item" in result["sql_preview"]
    assert "p_name => 'G_USER'" in result["sql_preview"]
    # APEX stores APPLICATION as short code 'APP' (col max 6)
    assert "p_scope => 'APP'" in result["sql_preview"]
    assert result["item_id"] == 8930


def test_add_app_item_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch, "_verify_app_item_exists")
    result = apex_add_app_item(app_id=100, item_id=8930, name="G_USER")
    assert result["dry_run"] is False
    assert result["item_id"] == 8930
    assert result["scope"] == "APPLICATION"
    fake_sess.execute.assert_called_once()
