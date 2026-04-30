"""Unit tests for tools/page_assets.py (Plan 2B-6 + chunked-LOB extension).

Coverage:
  * apex_add_page_js              - 1 test (deferred stub returns TOOL_DEFERRED)
  * apex_add_app_css              - 1 test (deferred stub returns TOOL_DEFERRED)
  * apex_add_static_app_file      - 10 tests (NOT_CONNECTED, PROD, TEST,
                                    DEV, CONTENT_TOO_LARGE, file_id passthrough,
                                    chunked dry-run preview, chunked DEV exec,
                                    chunk count math, oversize rejection at 1MB)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.audit.post_write_verify import MetadataSnapshot
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.page_assets import (
    apex_add_app_css,
    apex_add_page_js,
    apex_add_static_app_file,
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


def _patch_live_path(monkeypatch):
    fake_sess = MagicMock()
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_assets.ImportSession",
        lambda **kw: fake_sess,
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_assets.query_workspace_id",
        lambda profile, workspace: 100002,
    )
    snapshot_calls = iter(
        [
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
            (MetadataSnapshot(pages=25, regions=66, items=41), "DATA-LOADING"),
        ]
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_assets.query_metadata_snapshot",
        lambda profile, app_id: next(snapshot_calls),
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_assets.refresh_export",
        lambda **kw: {"skipped": True},
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.page_assets._verify_static_file_exists",
        lambda *a, **k: True,
    )
    return fake_sess


# ---------------------------------------------------------------------------
# Deferred tools
# ---------------------------------------------------------------------------


def test_add_page_js_deferred():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_page_js(app_id=100, page_id=1, javascript_code="console.log('x');")
    assert exc_info.value.code == "TOOL_DEFERRED"


def test_add_app_css_deferred():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_app_css(app_id=100, css_code="body { color: red; }")
    assert exc_info.value.code == "TOOL_DEFERRED"


# ---------------------------------------------------------------------------
# apex_add_static_app_file
# ---------------------------------------------------------------------------


def test_add_static_app_file_no_profile_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_static_app_file(
            app_id=100, file_name="x.css", file_content_text="body{}"
        )
    assert exc_info.value.code == "NOT_CONNECTED"


def test_add_static_app_file_rejects_on_prod():
    _setup_state(env="PROD")
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_static_app_file(
            app_id=100, file_name="x.css", file_content_text="body{}"
        )
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"


def test_add_static_app_file_rejects_oversize():
    """Files >1 MB are rejected (chunked-LOB upper bound)."""
    _setup_state(env="DEV")
    big = "x" * (1024 * 1024 + 1)  # 1 MB + 1 byte
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_add_static_app_file(
            app_id=100, file_name="big.css", file_content_text=big
        )
    assert exc_info.value.code == "CONTENT_TOO_LARGE"


def test_add_static_app_file_dry_run_on_test():
    _setup_state(env="TEST")
    result = apex_add_static_app_file(
        app_id=100,
        file_name="itest.css",
        file_content_text="body { color: red; }",
        mime_type="text/css",
    )
    assert result["dry_run"] is True
    assert "wwv_flow_imp_shared.create_app_static_file" in result["sql_preview"]
    assert "itest.css" in result["sql_preview"]
    assert "p_mime_type => 'text/css'" in result["sql_preview"]
    # The plsql preview should escape single quotes properly.
    assert result["mime_type"] == "text/css"
    assert result["content_bytes"] == len(b"body { color: red; }")


def test_add_static_app_file_executes_on_dev(monkeypatch):
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch)
    result = apex_add_static_app_file(
        app_id=100,
        file_name="hello.js",
        file_content_text="console.log('x');",
        mime_type="text/javascript",
    )
    assert result["dry_run"] is False
    assert result["file_name"] == "hello.js"
    assert result["mime_type"] == "text/javascript"
    fake_sess.execute.assert_called_once()


def test_add_static_app_file_dry_run_with_file_id():
    _setup_state(env="TEST")
    result = apex_add_static_app_file(
        app_id=100,
        file_name="x.txt",
        file_content_text="hi",
        file_id=9201,
    )
    assert result["dry_run"] is True
    assert "p_id => 9201" in result["sql_preview"]


def test_add_static_app_file_escapes_single_quotes():
    _setup_state(env="TEST")
    result = apex_add_static_app_file(
        app_id=100,
        file_name="quoted.txt",
        file_content_text="he said 'hi'",
    )
    assert result["dry_run"] is True
    # Ensure 'hi' inside content gets ''hi'' (Oracle quote-escaping)
    assert "''hi''" in result["sql_preview"]


# ---------------------------------------------------------------------------
# Chunked-LOB upload (>30 KB, ≤1 MB)
# ---------------------------------------------------------------------------


def test_add_static_app_file_chunked_dry_run_preview():
    """Content >30 KB switches to dbms_lob.createtemporary + append loop."""
    _setup_state(env="TEST")
    # 50 KB of ASCII content -> hex chunks; well above 30 KB threshold
    content = "x" * (50 * 1024)
    result = apex_add_static_app_file(
        app_id=100,
        file_name="big.css",
        file_content_text=content,
        mime_type="text/css",
    )
    assert result["dry_run"] is True
    preview = result["sql_preview"]
    # Chunked path uses dbms_lob.createtemporary, not utl_raw.cast_to_raw
    assert "dbms_lob.createtemporary" in preview
    assert "dbms_lob.append" in preview
    assert "hextoraw(" in preview
    assert "utl_raw.cast_to_raw" not in preview
    # Multiple chunks expected for 50 KB at 8 KB/chunk → 7 chunks
    assert preview.count("dbms_lob.append") >= 6
    assert result["content_bytes"] == 50 * 1024


def test_add_static_app_file_small_uses_single_cast():
    """Small content (≤30 KB) keeps the single utl_raw.cast_to_raw path."""
    _setup_state(env="TEST")
    content = "y" * (10 * 1024)  # 10 KB - well under threshold
    result = apex_add_static_app_file(
        app_id=100,
        file_name="small.css",
        file_content_text=content,
    )
    preview = result["sql_preview"]
    assert "utl_raw.cast_to_raw" in preview
    assert "dbms_lob.createtemporary" not in preview


def test_add_static_app_file_chunked_executes_on_dev(monkeypatch):
    """DEV path with chunked content invokes ImportSession.execute once."""
    _setup_state(env="DEV")
    fake_sess = _patch_live_path(monkeypatch)
    content = "z" * (40 * 1024)  # 40 KB
    result = apex_add_static_app_file(
        app_id=100,
        file_name="large.js",
        file_content_text=content,
        mime_type="text/javascript",
    )
    assert result["dry_run"] is False
    fake_sess.execute.assert_called_once()
    body = fake_sess.execute.call_args[0][0]
    assert "dbms_lob.createtemporary" in body
    assert "dbms_lob.append" in body
    assert "wwv_flow_imp_shared.create_app_static_file" in body


def test_add_static_app_file_chunk_count_matches_size():
    """Verify chunk math: 64 KB content at 8 KB/chunk → 8 chunks exactly."""
    _setup_state(env="TEST")
    content = "a" * (64 * 1024)
    result = apex_add_static_app_file(
        app_id=100,
        file_name="exact.css",
        file_content_text=content,
    )
    preview = result["sql_preview"]
    assert preview.count("dbms_lob.append") == 8


def test_add_static_app_file_accepts_at_one_mb():
    """Exactly 1 MB content is accepted (boundary inclusive)."""
    _setup_state(env="TEST")
    content = "b" * (1024 * 1024)  # exactly 1 MB
    result = apex_add_static_app_file(
        app_id=100,
        file_name="onembr.css",
        file_content_text=content,
    )
    assert result["dry_run"] is True
    assert result["content_bytes"] == 1024 * 1024
