from __future__ import annotations

from unittest.mock import MagicMock

from apex_builder_mcp.tools.inspect_apex import (
    apex_describe_acl,
    apex_describe_app,
    apex_describe_page,
    apex_list_apps,
    apex_list_pages,
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
