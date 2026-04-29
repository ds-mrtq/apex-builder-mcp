"""Runtime URL check helper for APEX pages.

Phase 0 findings:
- nginx in front of ORDS rejects requests without browser User-Agent (returns 410)
- ORDS returns 302 -> /login or /sign-in for auth-protected pages -- that 302
  proves the page is registered. Don't follow auth redirects (cookie jar
  needed -> infinite loop).
"""
from __future__ import annotations

import urllib.error
import urllib.request

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def build_runtime_url(prefix: str, app_alias: str, page_id: int) -> str:
    """Build APEX runtime URL: <prefix>/<app_alias_lower>/<page_id>."""
    return f"{prefix.rstrip('/')}/{app_alias.lower()}/{page_id}"


def check_page(prefix: str, app_alias: str, page_id: int, timeout: int = 30) -> tuple[bool, str]:
    """GET runtime URL with browser UA. Accept 200 or 302->login as PASS.

    Returns (success, info_message).
    """
    url = build_runtime_url(prefix, app_alias, page_id)
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    try:
        resp = opener.open(req, timeout=timeout)  # noqa: S310
        try:
            html = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            location = resp.headers.get("Location", "")
        finally:
            resp.close()
    except urllib.error.HTTPError as e:
        status = e.code
        location = e.headers.get("Location", "") if e.headers else ""
        try:
            html = e.read().decode("utf-8", errors="replace")
        except Exception:
            html = ""
    except Exception as e:
        return (False, f"{url} -> {type(e).__name__}: {e}")

    if status in (301, 302, 303, 307, 308):
        loc_lower = location.lower()
        if "/login" in loc_lower or "/sign-in" in loc_lower or "session=" in loc_lower:
            return (True, f"{url} -> {status} -> {location} (auth redirect = page registered)")
        return (True, f"{url} -> {status} -> {location}")
    if status == 200:
        for marker in ["application not found", "page not found", "ORA-", "<title>Error"]:
            if marker in html:
                return (False, f"{url} -> 200 but contains '{marker}'")
        return (True, f"{url} -> HTTP 200, no error markers")
    return (False, f"{url} -> HTTP {status}")
