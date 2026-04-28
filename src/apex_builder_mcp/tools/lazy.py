# src/apex_builder_mcp/tools/lazy.py
from __future__ import annotations

from typing import Any

from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.lazy_loader import LazyToolLoader, NotLoadableError
from apex_builder_mcp.registry.tool_decorator import apex_tool

# Module-level loader
_LOADER: LazyToolLoader | None = None


def _get_loader() -> LazyToolLoader:
    global _LOADER
    if _LOADER is None:
        _LOADER = LazyToolLoader()
        _LOADER.bootstrap()
    return _LOADER


def _reset_loader_for_tests() -> None:
    global _LOADER
    _LOADER = None


@apex_tool(name="apex_categories_list", category=Category.LAZY_META)
def apex_categories_list() -> dict[str, Any]:
    loader = _get_loader()
    loaded = {c.value for c in loader.loaded_categories()}
    return {
        "categories": [
            {
                "name": c.value,
                "always_loaded": c.always_loaded,
                "auto_loaded_after_connect": c.auto_loaded_after_connect,
                "currently_loaded": c.value in loaded,
            }
            for c in Category
        ],
        "loaded": sorted(loaded),
    }


@apex_tool(name="apex_load_category", category=Category.LAZY_META)
def apex_load_category(name: str) -> dict[str, Any]:
    loader = _get_loader()
    cat = Category(name)
    loader.load(cat)
    loaded = {c.value for c in loader.loaded_categories()}
    return {"loaded": sorted(loaded)}


@apex_tool(name="apex_unload_category", category=Category.LAZY_META)
def apex_unload_category(name: str) -> dict[str, Any]:
    loader = _get_loader()
    cat = Category(name)
    try:
        loader.unload(cat)
    except NotLoadableError as e:
        raise Exception(f"Category {name} is always-loaded; cannot unload") from e
    loaded = {c.value for c in loader.loaded_categories()}
    return {"loaded": sorted(loaded)}
