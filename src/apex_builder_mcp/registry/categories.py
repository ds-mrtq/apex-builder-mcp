# src/apex_builder_mcp/registry/categories.py
from __future__ import annotations

from collections import defaultdict
from enum import StrEnum


class Category(StrEnum):
    CORE = "core"
    LAZY_META = "lazy_meta"
    AUDIT_BASICS = "audit_basics"
    AUDIT_AUX = "audit_aux"
    READ_DB = "read_db"
    READ_APEX = "read_apex"
    WRITE_CORE = "write_core"
    BRIDGES = "bridges"

    @property
    def always_loaded(self) -> bool:
        return self in {
            Category.CORE,
            Category.LAZY_META,
            Category.AUDIT_BASICS,
            Category.AUDIT_AUX,
        }

    @property
    def auto_loaded_after_connect(self) -> bool:
        return self in {Category.READ_DB, Category.READ_APEX}


class CategoryRegistry:
    """Tracks which tool names belong to which category."""

    def __init__(self) -> None:
        self._by_category: dict[Category, list[str]] = defaultdict(list)

    def add(self, category: Category, tool_name: str) -> None:
        if tool_name not in self._by_category[category]:
            self._by_category[category].append(tool_name)

    def tools_in(self, category: Category) -> list[str]:
        return list(self._by_category.get(category, []))

    def all_categories(self) -> list[Category]:
        return list(self._by_category.keys())
