from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

from apex_builder_mcp.apex_api.runtime_check import build_runtime_url, check_page


def test_build_runtime_url_lowercases_alias():
    url = build_runtime_url(
        prefix="https://apexdev.vicemhatien.com.vn/ords/r/ereport",
        app_alias="DATA-LOADING",
        page_id=8000,
    )
    assert url == "https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/8000"


def test_build_runtime_url_strips_trailing_slash():
    url = build_runtime_url(
        prefix="https://x/ords/r/ws/",
        app_alias="APP",
        page_id=1,
    )
    assert url == "https://x/ords/r/ws/app/1"


def test_check_page_accepts_302_to_login():
    """302 to /login = page registered (auth required)."""
    err = urllib.error.HTTPError(
        "u", 302, "Found",
        {"Location": "https://x/data-loading/login?session=abc"},
        None,
    )
    err.headers = MagicMock()
    _loc = "https://x/data-loading/login?session=abc"
    err.headers.get = lambda k, d="": _loc if k == "Location" else d
    err.read = lambda: b""

    with patch(
        "apex_builder_mcp.apex_api.runtime_check.urllib.request.OpenerDirector.open",
        side_effect=err,
    ):
        ok, info = check_page("https://x", "data-loading", 8000)

    assert ok is True
    assert "auth redirect" in info or "login" in info


def test_check_page_accepts_200():
    """Direct 200 with no error markers = pass."""
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.headers.get = lambda k, d="": d
    fake_resp.read = lambda: b"<html><body>Hello</body></html>"
    fake_resp.close = MagicMock()

    with patch(
        "apex_builder_mcp.apex_api.runtime_check.urllib.request.OpenerDirector.open",
        return_value=fake_resp,
    ):
        ok, info = check_page("https://x", "app", 1)

    assert ok is True
    assert "200" in info


def test_check_page_rejects_200_with_error_marker():
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.headers.get = lambda k, d="": d
    fake_resp.read = lambda: b"<html><title>Error</title></html>"
    fake_resp.close = MagicMock()

    with patch(
        "apex_builder_mcp.apex_api.runtime_check.urllib.request.OpenerDirector.open",
        return_value=fake_resp,
    ):
        ok, info = check_page("https://x", "app", 1)

    assert ok is False
    assert "Error" in info or "error" in info


def test_check_page_handles_exception():
    with patch(
        "apex_builder_mcp.apex_api.runtime_check.urllib.request.OpenerDirector.open",
        side_effect=ConnectionError("connection refused"),
    ):
        ok, info = check_page("https://x", "app", 1)

    assert ok is False
    assert "ConnectionError" in info
