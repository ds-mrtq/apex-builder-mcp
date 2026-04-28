# tests/unit/test_entrypoint.py
from __future__ import annotations

import asyncio

from apex_builder_mcp.__main__ import build_server


def test_build_server_returns_fastmcp_app():
    server = build_server()
    assert server is not None


def test_only_always_loaded_visible_at_startup():
    server = build_server()
    # FastMCP 3.2.4: list_tools is async; run via asyncio.run.
    tools = asyncio.run(server.list_tools())
    tool_names = [t.name for t in tools]

    assert tool_names, "FastMCP server has no registered tools"

    # Always-loaded tools must be present
    for required in ("apex_status", "apex_categories_list", "apex_snapshot_acl"):
        assert required in tool_names, f"missing {required}; got {tool_names}"

    # Lazy categories (READ_DB, READ_APEX, WRITE_CORE, BRIDGES) tools must NOT
    # be registered at startup. We don't have such tools yet, but verify by
    # confirming nothing outside known always-loaded categories slipped in.
    from apex_builder_mcp.registry.tool_decorator import get_registered_tools

    lazy_tool_names = {
        t.name for t in get_registered_tools() if not t.category.always_loaded
    }
    for lazy_name in lazy_tool_names:
        assert lazy_name not in tool_names, f"lazy tool {lazy_name} should not be loaded at startup"
