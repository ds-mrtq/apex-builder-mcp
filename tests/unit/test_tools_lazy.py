# tests/unit/test_tools_lazy.py
from __future__ import annotations

import pytest

from apex_builder_mcp.tools.lazy import (
    apex_categories_list,
    apex_load_category,
    apex_unload_category,
)


def test_categories_list_includes_mvp_categories():
    result = apex_categories_list()
    names = {c["name"] for c in result["categories"]}
    for required in ("core", "lazy_meta", "read_db", "read_apex", "write_core", "bridges"):
        assert required in names


def test_load_category_marks_loaded():
    result = apex_load_category(name="write_core")
    assert "write_core" in result["loaded"]


def test_unload_always_loaded_rejects():
    with pytest.raises(Exception) as exc_info:
        apex_unload_category(name="core")
    assert "always" in str(exc_info.value).lower()
