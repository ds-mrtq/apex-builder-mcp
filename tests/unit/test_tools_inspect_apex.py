from __future__ import annotations

from unittest.mock import MagicMock

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


def _mock_pool(monkeypatch, fetchall_returns=None, fetchone_returns=None):
    fake_cur = MagicMock()
    if fetchall_returns is not None:
        fake_cur.fetchall.side_effect = fetchall_returns
    if fetchone_returns is not None:
        fake_cur.fetchone.side_effect = fetchone_returns
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    return fake_cur


def test_list_apps_returns_dict(monkeypatch):
    _mock_pool(
        monkeypatch,
        fetchall_returns=[[(100, "Data Loading", "DATA-LOADING", 25)]],
    )
    result = apex_list_apps(workspace="EREPORT")
    assert result["count"] == 1
    assert result["apps"][0]["application_id"] == 100


def test_list_apps_no_workspace(monkeypatch):
    _mock_pool(
        monkeypatch,
        fetchall_returns=[[(100, "App", "ALIAS", 5), (101, "App2", "ALIAS2", 3)]],
    )
    result = apex_list_apps()
    assert result["count"] == 2


def test_describe_app_found(monkeypatch):
    _mock_pool(
        monkeypatch,
        fetchone_returns=[
            ("Data Loading", "DATA-LOADING", 25, "EREPORT", "PUBLIC", "STANDARD"),
            (3,),
        ],
    )
    result = apex_describe_app(app_id=100)
    assert result["application_id"] == 100
    assert result["application_name"] == "Data Loading"
    assert result["lov_count"] == 3


def test_describe_app_not_found(monkeypatch):
    _mock_pool(monkeypatch, fetchone_returns=[None])
    result = apex_describe_app(app_id=999)
    assert result["found"] is False


def test_list_pages_returns_pages(monkeypatch):
    _mock_pool(
        monkeypatch,
        fetchall_returns=[[(0, "Global Page"), (1, "Home"), (2, "Import")]],
    )
    result = apex_list_pages(app_id=100)
    assert result["count"] == 3


def test_describe_page_with_components(monkeypatch):
    _mock_pool(
        monkeypatch,
        fetchone_returns=[("Home", "HOME", "STANDARD", "Y")],
        fetchall_returns=[
            [(1000, "Hero", "BODY", 10)],
            [(2000, "P1_X", "TEXT", 1000)],
            [(3000, "BTN_OK", 1000, "SUBMIT")],
            [(4000, "PROC_X", "PLSQL", 100)],
        ],
    )
    result = apex_describe_page(app_id=100, page_id=1)
    assert result["page_id"] == 1
    assert len(result["regions"]) == 1
    assert len(result["items"]) == 1


def test_describe_page_not_found(monkeypatch):
    _mock_pool(monkeypatch, fetchone_returns=[None])
    result = apex_describe_page(app_id=100, page_id=999)
    assert result["found"] is False


def test_describe_acl(monkeypatch):
    _mock_pool(
        monkeypatch,
        fetchall_returns=[[("CONGNC", "ADMIN"), ("OPS_USER", "OPERATOR")]],
    )
    result = apex_describe_acl(app_id=100)
    assert result["count"] == 2
    assert result["assignments"][0]["user_name"] == "CONGNC"


def test_get_page_details_returns_full(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = (
        "Home", "HOME", "STANDARD", "Y",
        "page_func", 1234, "navlist",
        None, "Desktop", "css", "js", "#DEFAULT#",
    )
    fake_cur.description = [
        ("PAGE_NAME", None, None, None, None, None, None),
        ("PAGE_ALIAS", None, None, None, None, None, None),
        ("PAGE_MODE", None, None, None, None, None, None),
        ("REQUIRES_AUTHENTICATION", None, None, None, None, None, None),
        ("PAGE_FUNCTION", None, None, None, None, None, None),
        ("PAGE_TEMPLATE", None, None, None, None, None, None),
        ("PRIMARY_NAVIGATION_LIST", None, None, None, None, None, None),
        ("SECURITY_AUTHORIZATION_SCHEME", None, None, None, None, None, None),
        ("PRIMARY_USER_INTERFACE", None, None, None, None, None, None),
        ("INLINE_CSS", None, None, None, None, None, None),
        ("JAVASCRIPT_CODE_ONLOAD", None, None, None, None, None, None),
        ("PAGE_TEMPLATE_OPTIONS", None, None, None, None, None, None),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_get_page_details(app_id=100, page_id=1)
    assert result["found"] is True
    assert result["details"]["PAGE_NAME"] == "Home"


def test_get_page_details_not_found(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = None
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_get_page_details(app_id=999, page_id=1)
    assert result["found"] is False


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


def test_list_regions(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        (1000, "Hero", "BODY", 10, "t-Region", None, "STATIC"),
        (1001, "Body", "BODY", 20, "t-Region", "select 1 from dual", "QUERY"),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_list_regions(app_id=100, page_id=1)
    assert result["count"] == 2
    assert result["regions"][0]["region_name"] == "Hero"


def test_list_items(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        (2000, "P1_X", "TEXT", 1000, 10, "X label", "X prompt"),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_list_items(app_id=100, page_id=1)
    assert result["count"] == 1
    assert result["items"][0]["name"] == "P1_X"


def test_list_processes(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        (4000, "PROC_OK", "NATIVE_PLSQL", 10, "AFTER_SUBMIT", "begin null; end;"),
        (4001, "PROC_LOG", "NATIVE_PLSQL", 20, "BEFORE_HEADER", None),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_list_processes(app_id=100, page_id=1)
    assert result["count"] == 2
    assert result["processes"][0]["name"] == "PROC_OK"
    assert result["processes"][0]["code"] == "begin null; end;"
    assert result["processes"][1]["code"] is None


def test_list_workspace_users(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        ("EREPORT", "ADMIN", "admin@example.com", "Yes", "Yes", "No", None),
        ("EREPORT", "DEV1", "dev1@example.com", "No", "Yes", "No", None),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_list_workspace_users(workspace="EREPORT")
    assert result["count"] == 2
    assert result["workspace"] == "EREPORT"
    assert result["users"][0]["user_name"] == "ADMIN"
    assert result["users"][0]["is_admin"] == "Yes"
    assert result["users"][1]["is_developer"] == "Yes"


def test_list_workspace_users_no_filter(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        ("EREPORT", "ADMIN", "a@x", "Yes", "Yes", "No", None),
        ("OTHER_WS", "USER1", "u@x", "No", "Yes", "No", None),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_list_workspace_users()
    assert result["count"] == 2
    assert result["workspace"] is None


def test_list_dynamic_actions(monkeypatch):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        (5000, "DA_X", "click", "JQUERY_SELECTOR", "#P1_BUTTON"),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr(
        "apex_builder_mcp.tools.inspect_apex._get_pool", lambda: fake_pool
    )
    result = apex_list_dynamic_actions(app_id=100, page_id=1)
    assert result["count"] == 1
    assert result["dynamic_actions"][0]["name"] == "DA_X"
    assert result["dynamic_actions"][0]["event"] == "click"
