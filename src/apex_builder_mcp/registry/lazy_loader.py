# src/apex_builder_mcp/registry/lazy_loader.py
from __future__ import annotations

from collections.abc import Callable

from apex_builder_mcp.registry.categories import Category


class NotLoadableError(RuntimeError):
    pass


class LazyToolLoader:
    """Tracks which categories are 'loaded' (visible to LLM) and notifies via FastMCP."""

    def __init__(self) -> None:
        self._loaded: set[Category] = set()
        self._notify: Callable[[], None] | None = None

    def bootstrap(self) -> None:
        for cat in Category:
            if cat.always_loaded:
                self._loaded.add(cat)

    def loaded_categories(self) -> set[Category]:
        return set(self._loaded)

    def set_notify_callback(self, fn: Callable[[], None]) -> None:
        self._notify = fn

    def load(self, category: Category) -> None:
        if category in self._loaded:
            return
        self._loaded.add(category)
        self._fire_notify()

    def unload(self, category: Category) -> None:
        if category.always_loaded:
            raise NotLoadableError(f"Category {category.value} is always-loaded; cannot unload")
        if category not in self._loaded:
            return
        self._loaded.remove(category)
        self._fire_notify()

    def on_post_connect(self) -> None:
        for cat in Category:
            if cat.auto_loaded_after_connect:
                self.load(cat)

    def _fire_notify(self) -> None:
        if self._notify is not None:
            self._notify()
