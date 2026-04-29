from __future__ import annotations

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.inspect_apex import (
    apex_describe_acl,
    apex_describe_app,
    apex_describe_page,
    apex_describe_page_human,
    apex_get_page_details,
    apex_list_apps,
    apex_list_dynamic_actions,
    apex_list_items,
    apex_list_pages,
    apex_list_processes,
    apex_list_regions,
    apex_list_workspace_users,
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
# apex_list_apps
# ---------------------------------------------------------------------------


def test_list_apps_returns_dict(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_list_apps",
        lambda profile, workspace: [
            {"application_id": 100, "application_name": "Data Loading",
             "alias": "DATA-LOADING", "pages": 25}
        ],
    )
    result = apex_list_apps(workspace="EREPORT")
    assert result["count"] == 1
    assert result["apps"][0]["application_id"] == 100


def test_list_apps_no_workspace(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_list_apps",
        lambda profile, workspace: [
            {"application_id": 100, "application_name": "App",
             "alias": "ALIAS", "pages": 5},
            {"application_id": 101, "application_name": "App2",
             "alias": "ALIAS2", "pages": 3},
        ],
    )
    result = apex_list_apps()
    assert result["count"] == 2


def test_list_apps_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_apps()
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_describe_app
# ---------------------------------------------------------------------------


def test_describe_app_found(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_describe_app",
        lambda profile, app_id: {
            "application_name": "Data Loading",
            "alias": "DATA-LOADING",
            "pages": 25,
            "owner": "EREPORT",
            "authentication_scheme": "PUBLIC",
            "page_template": "STANDARD",
            "lov_count": 3,
        },
    )
    result = apex_describe_app(app_id=100)
    assert result["application_id"] == 100
    assert result["application_name"] == "Data Loading"
    assert result["lov_count"] == 3
    assert result["found"] is True


def test_describe_app_not_found(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_describe_app",
        lambda profile, app_id: None,
    )
    result = apex_describe_app(app_id=999)
    assert result["found"] is False


def test_describe_app_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_describe_app(app_id=100)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_list_pages
# ---------------------------------------------------------------------------


def test_list_pages_returns_pages(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_list_pages",
        lambda profile, app_id: [
            {"page_id": 0, "page_name": "Global Page"},
            {"page_id": 1, "page_name": "Home"},
            {"page_id": 2, "page_name": "Import"},
        ],
    )
    result = apex_list_pages(app_id=100)
    assert result["count"] == 3


def test_list_pages_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_pages(app_id=100)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_describe_page
# ---------------------------------------------------------------------------


def test_describe_page_with_components(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_describe_page",
        lambda profile, app_id, page_id: {
            "page_name": "Home",
            "page_alias": "HOME",
            "page_mode": "STANDARD",
            "requires_authentication": "Y",
            "regions": [
                {"region_id": 1000, "name": "Hero", "position": "BODY", "sequence": 10}
            ],
            "items": [
                {"item_id": 2000, "name": "P1_X", "display_as": "TEXT", "region_id": 1000}
            ],
            "buttons": [
                {"button_id": 3000, "name": "BTN_OK", "region_id": 1000, "action": "SUBMIT"}
            ],
            "processes": [
                {"process_id": 4000, "name": "PROC_X", "type": "PLSQL", "sequence": 100}
            ],
        },
    )
    result = apex_describe_page(app_id=100, page_id=1)
    assert result["page_id"] == 1
    assert len(result["regions"]) == 1
    assert len(result["items"]) == 1
    assert result["found"] is True


def test_describe_page_not_found(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_describe_page",
        lambda profile, app_id, page_id: None,
    )
    result = apex_describe_page(app_id=100, page_id=999)
    assert result["found"] is False


def test_describe_page_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_describe_page(app_id=100, page_id=1)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_describe_acl
# ---------------------------------------------------------------------------


def test_describe_acl(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_describe_acl",
        lambda profile, app_id: [
            {"user_name": "CONGNC", "role_static_id": "ADMIN"},
            {"user_name": "OPS_USER", "role_static_id": "OPERATOR"},
        ],
    )
    result = apex_describe_acl(app_id=100)
    assert result["count"] == 2
    assert result["assignments"][0]["user_name"] == "CONGNC"


def test_describe_acl_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_describe_acl(app_id=100)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_get_page_details
# ---------------------------------------------------------------------------


def test_get_page_details_returns_full(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_page_details",
        lambda profile, app_id, page_id: {
            "PAGE_NAME": "Home",
            "PAGE_ALIAS": "HOME",
            "PAGE_MODE": "STANDARD",
            "REQUIRES_AUTHENTICATION": "Y",
            "PAGE_FUNCTION": "page_func",
            "PAGE_TEMPLATE": 1234,
            "PRIMARY_NAVIGATION_LIST": "navlist",
            "SECURITY_AUTHORIZATION_SCHEME": None,
            "PRIMARY_USER_INTERFACE": "Desktop",
            "INLINE_CSS": "css",
            "JAVASCRIPT_CODE_ONLOAD": "js",
            "PAGE_TEMPLATE_OPTIONS": "#DEFAULT#",
        },
    )
    result = apex_get_page_details(app_id=100, page_id=1)
    assert result["found"] is True
    assert result["details"]["PAGE_NAME"] == "Home"


def test_get_page_details_not_found(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_page_details",
        lambda profile, app_id, page_id: None,
    )
    result = apex_get_page_details(app_id=999, page_id=1)
    assert result["found"] is False


def test_get_page_details_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_get_page_details(app_id=100, page_id=1)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_describe_page_human (composes apex_describe_page)
# ---------------------------------------------------------------------------


def test_describe_page_human_returns_markdown(monkeypatch):
    # Mock apex_describe_page to return synthetic page
    def fake_describe(app_id, page_id):
        return {
            "app_id": 100, "page_id": 1, "found": True,
            "page_name": "Home", "page_alias": "HOME", "page_mode": "STANDARD",
            "requires_authentication": "Y",
            "regions": [{"region_id": 1000, "name": "Hero", "position": "BODY", "sequence": 10}],
            "items": [{"item_id": 2000, "name": "P1_X", "display_as": "TEXT", "region_id": 1000}],
            "buttons": [{"button_id": 3000, "name": "OK", "region_id": 1000, "action": "SUBMIT"}],
            "processes": [{"process_id": 4000, "name": "PROC", "type": "PLSQL", "sequence": 10}],
        }
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.apex_describe_page", fake_describe
    )
    result = apex_describe_page_human(app_id=100, page_id=1)
    assert result["found"] is True
    assert "# Page 1: Home" in result["summary"]
    assert "Hero" in result["summary"]
    assert "P1_X" in result["summary"]


# ---------------------------------------------------------------------------
# apex_list_regions
# ---------------------------------------------------------------------------


def test_list_regions(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_list_regions",
        lambda profile, app_id, page_id: [
            {"region_id": 1000, "region_name": "Hero", "position": "BODY",
             "sequence": 10, "template": "t-Region", "source": None,
             "source_type": "STATIC"},
            {"region_id": 1001, "region_name": "Body", "position": "BODY",
             "sequence": 20, "template": "t-Region",
             "source": "select 1 from dual", "source_type": "QUERY"},
        ],
    )
    result = apex_list_regions(app_id=100, page_id=1)
    assert result["count"] == 2
    assert result["regions"][0]["region_name"] == "Hero"


def test_list_regions_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_regions(app_id=100, page_id=1)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_list_items
# ---------------------------------------------------------------------------


def test_list_items(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_list_items",
        lambda profile, app_id, page_id: [
            {"item_id": 2000, "name": "P1_X", "display_as": "TEXT",
             "region_id": 1000, "sequence": 10,
             "label": "X label", "prompt": "X prompt"},
        ],
    )
    result = apex_list_items(app_id=100, page_id=1)
    assert result["count"] == 1
    assert result["items"][0]["name"] == "P1_X"


def test_list_items_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_items(app_id=100, page_id=1)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_list_processes
# ---------------------------------------------------------------------------


def test_list_processes(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_list_processes",
        lambda profile, app_id, page_id: [
            {"process_id": 4000, "name": "PROC_OK", "type": "NATIVE_PLSQL",
             "sequence": 10, "point": "AFTER_SUBMIT", "code": "begin null; end;"},
            {"process_id": 4001, "name": "PROC_LOG", "type": "NATIVE_PLSQL",
             "sequence": 20, "point": "BEFORE_HEADER", "code": None},
        ],
    )
    result = apex_list_processes(app_id=100, page_id=1)
    assert result["count"] == 2
    assert result["processes"][0]["name"] == "PROC_OK"
    assert result["processes"][0]["code"] == "begin null; end;"
    assert result["processes"][1]["code"] is None


def test_list_processes_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_processes(app_id=100, page_id=1)
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_list_workspace_users (already wired through query_workspace_users)
# ---------------------------------------------------------------------------


def test_list_workspace_users(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_workspace_users",
        lambda profile, workspace: [
            {
                "workspace_name": "EREPORT",
                "user_name": "ADMIN",
                "email": "admin@example.com",
                "is_admin": "Yes",
                "is_developer": "Yes",
                "account_locked": "No",
                "last_login": None,
            },
            {
                "workspace_name": "EREPORT",
                "user_name": "DEV1",
                "email": "dev1@example.com",
                "is_admin": "No",
                "is_developer": "Yes",
                "account_locked": "No",
                "last_login": None,
            },
        ],
    )
    result = apex_list_workspace_users(workspace="EREPORT")
    assert result["count"] == 2
    assert result["workspace"] == "EREPORT"
    assert result["users"][0]["user_name"] == "ADMIN"
    assert result["users"][0]["is_admin"] == "Yes"
    assert result["users"][1]["is_developer"] == "Yes"


def test_list_workspace_users_no_filter(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_workspace_users",
        lambda profile, workspace: [
            {
                "workspace_name": "EREPORT",
                "user_name": "ADMIN",
                "email": "a@x",
                "is_admin": "Yes",
                "is_developer": "Yes",
                "account_locked": "No",
                "last_login": None,
            },
            {
                "workspace_name": "OTHER_WS",
                "user_name": "USER1",
                "email": "u@x",
                "is_admin": "No",
                "is_developer": "Yes",
                "account_locked": "No",
                "last_login": None,
            },
        ],
    )
    result = apex_list_workspace_users()
    assert result["count"] == 2
    assert result["workspace"] is None


def test_list_workspace_users_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_workspace_users()
    assert exc_info.value.code == "NOT_CONNECTED"


# ---------------------------------------------------------------------------
# apex_list_dynamic_actions
# ---------------------------------------------------------------------------


def test_list_dynamic_actions(monkeypatch):
    _setup_state()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex.query_list_dynamic_actions",
        lambda profile, app_id, page_id: [
            {"da_id": 5000, "name": "DA_X", "event": "click",
             "element_type": "JQUERY_SELECTOR", "element": "#P1_BUTTON"},
        ],
    )
    result = apex_list_dynamic_actions(app_id=100, page_id=1)
    assert result["count"] == 1
    assert result["dynamic_actions"][0]["name"] == "DA_X"
    assert result["dynamic_actions"][0]["event"] == "click"


def test_list_dynamic_actions_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_list_dynamic_actions(app_id=100, page_id=1)
    assert exc_info.value.code == "NOT_CONNECTED"
