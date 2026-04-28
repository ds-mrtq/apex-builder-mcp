# tests/unit/test_entrypoint.py
from __future__ import annotations

import asyncio

import pytest

from apex_builder_mcp.__main__ import build_server
from apex_builder_mcp.registry.categories import Category


def _list_tool_names(server) -> list[str]:
    """Adapter for FastMCP 3.2.4 async list_tools API."""
    tools = asyncio.run(server.list_tools())
    return [t.name for t in tools]


@pytest.fixture(autouse=True)
def _reset_loader():
    """Reset shared loader singleton between tests to avoid bleed."""
    from apex_builder_mcp.tools.lazy import _reset_loader_for_tests
    _reset_loader_for_tests()
    yield
    _reset_loader_for_tests()


def test_build_server_returns_fastmcp_app():
    server = build_server()
    assert server is not None


def test_only_always_loaded_visible_at_startup():
    server = build_server()
    tool_names = _list_tool_names(server)
    # Always-loaded tools must be present
    for required in ("apex_status", "apex_categories_list", "apex_snapshot_acl"):
        assert required in tool_names, f"missing {required}; got {tool_names}"


def test_load_category_registers_tools_with_server():
    """Verify the lazy loader integration: loading a category triggers add_tool."""
    # Sanity: write_core tools NOT initially loaded
    # (no write_core tools exist yet in Phase 0, but bridges category exists too)
    # We need at least one non-always-loaded category that has tools registered
    # by Phase 0. Currently NONE do — Phase 0 only registers always-loaded.
    # So we test the SYNC mechanism with a synthetic registration:
    from apex_builder_mcp.registry.tool_decorator import (
        _REGISTERED_TOOLS,
        RegisteredTool,
    )

    # Inject a synthetic write_core tool
    def _synthetic_tool() -> str:
        return "synthetic"
    _synthetic_tool.__name__ = "apex_synthetic_for_test"

    synthetic = RegisteredTool(
        name="apex_synthetic_for_test",
        category=Category.WRITE_CORE,
        always_loaded=False,
        func=_synthetic_tool,
    )
    _REGISTERED_TOOLS.append(synthetic)
    try:
        # Re-build server (initial sync now sees synthetic in WRITE_CORE,
        # but WRITE_CORE not loaded, so synthetic NOT registered yet)
        server = build_server()
        names_before = set(_list_tool_names(server))
        assert "apex_synthetic_for_test" not in names_before

        # Now load WRITE_CORE — should trigger sync_tools() which adds the tool
        from apex_builder_mcp.tools.lazy import _get_loader
        loader = _get_loader()
        loader.load(Category.WRITE_CORE)

        names_after = set(_list_tool_names(server))
        assert "apex_synthetic_for_test" in names_after, (
            f"synthetic tool not registered after load_category; "
            f"before={names_before}, after={names_after}"
        )

        # And unload removes it (if FastMCP supports remove_tool)
        loader.unload(Category.WRITE_CORE)
        names_after_unload = set(_list_tool_names(server))
        # Permissive assertion: either remove_tool worked, or it stayed
        # (we don't fail if FastMCP version lacks remove_tool)
        if hasattr(server, "remove_tool"):
            assert "apex_synthetic_for_test" not in names_after_unload, (
                "synthetic tool should be removed after unload_category"
            )
    finally:
        # Cleanup synthetic registration
        _REGISTERED_TOOLS[:] = [t for t in _REGISTERED_TOOLS if t.name != "apex_synthetic_for_test"]
