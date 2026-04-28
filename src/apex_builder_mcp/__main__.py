# src/apex_builder_mcp/__main__.py
from __future__ import annotations

from fastmcp import FastMCP

from apex_builder_mcp.registry.lazy_loader import LazyToolLoader
from apex_builder_mcp.registry.tool_decorator import get_registered_tools

# Side-effect imports: tool modules' @apex_tool decorators populate the registry.
from apex_builder_mcp.tools import audit as _audit  # noqa: F401
from apex_builder_mcp.tools import connection as _conn  # noqa: F401
from apex_builder_mcp.tools import lazy as _lazy  # noqa: F401


def build_server() -> FastMCP:
    """Build the FastMCP server with only always-loaded tools registered.

    Lazy categories (READ_DB, READ_APEX, WRITE_CORE, BRIDGES) are NOT
    registered at startup. They are loaded later via apex_load_category
    or auto-loaded after apex_connect.
    """
    server: FastMCP = FastMCP("apex-builder-mcp")
    loader = LazyToolLoader()
    loader.bootstrap()

    def notify_changed() -> None:
        # FastMCP 3.x emits tools/list_changed automatically when add_tool /
        # remove_tool is called on the live server. If the installed version
        # exposes an explicit method, prefer it; otherwise this is a no-op.
        for method_name in (
            "send_tools_list_changed",
            "notify_tools_changed",
            "_send_list_changed",
        ):
            method = getattr(server, method_name, None)
            if method is not None:
                method()
                return

    loader.set_notify_callback(notify_changed)

    loaded_cats = loader.loaded_categories()
    for tool in get_registered_tools():
        if tool.category in loaded_cats:
            server.add_tool(tool.func)
    return server


def main() -> None:
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
