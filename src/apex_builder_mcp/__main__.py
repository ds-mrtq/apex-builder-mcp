# src/apex_builder_mcp/__main__.py
from __future__ import annotations

from fastmcp import FastMCP

from apex_builder_mcp.registry.tool_decorator import get_registered_tools

# Import tool modules so decorators register them
from apex_builder_mcp.tools import audit as _audit  # noqa: F401
from apex_builder_mcp.tools import connection as _conn  # noqa: F401
from apex_builder_mcp.tools import lazy as _lazy  # noqa: F401
from apex_builder_mcp.tools.lazy import _get_loader


def build_server() -> FastMCP:
    """Build a FastMCP server wired to the shared LazyToolLoader.

    The loader's notify callback syncs the server's tool registry with
    the loader's loaded_categories(): newly-loaded categories add their
    tools via server.add_tool, newly-unloaded categories remove via
    server.remove_tool (FastMCP auto-emits tools/list_changed).
    """
    server = FastMCP("apex-builder-mcp")
    loader = _get_loader()  # SAME singleton as tools/lazy.py uses

    # Track which tool names we have registered with the server.
    _registered_tool_names: set[str] = set()

    def sync_tools() -> None:
        """Sync server's tool registry with loader.loaded_categories()."""
        loaded_cats = loader.loaded_categories()
        desired = {
            t.name: t for t in get_registered_tools() if t.category in loaded_cats
        }
        # Register newly-loaded tools
        for name, tool in desired.items():
            if name not in _registered_tool_names:
                server.add_tool(tool.func)
                _registered_tool_names.add(name)
        # Deregister newly-unloaded tools
        to_remove = _registered_tool_names - set(desired.keys())
        for name in list(to_remove):
            remove_method = getattr(server, "remove_tool", None)
            if callable(remove_method):
                try:
                    remove_method(name)
                except Exception:
                    # Tool may not be removable on this FastMCP version;
                    # swallow so unload still updates loader state.
                    pass
            _registered_tool_names.discard(name)

    loader.set_notify_callback(sync_tools)

    # Initial sync registers all always-loaded tools
    sync_tools()

    return server


def main() -> None:
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
