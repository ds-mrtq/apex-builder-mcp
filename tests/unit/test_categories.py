# tests/unit/test_categories.py
from __future__ import annotations

from apex_builder_mcp.registry.categories import Category, CategoryRegistry
from apex_builder_mcp.registry.tool_decorator import apex_tool, get_registered_tools


def test_categories_enum_has_mvp_categories():
    names = {c.value for c in Category}
    for required in ("core", "lazy_meta", "audit_basics", "audit_aux", "read_db", "read_apex"):
        assert required in names


def test_register_tool_with_decorator():
    @apex_tool(name="apex_test_tool", category=Category.CORE)
    def f() -> str:
        return "ok"

    tools = get_registered_tools()
    matches = [t for t in tools if t.name == "apex_test_tool"]
    assert len(matches) == 1
    assert matches[0].category == Category.CORE
    assert matches[0].always_loaded is True  # core is always loaded


def test_registry_groups_by_category():
    reg = CategoryRegistry()
    reg.add(Category.CORE, "tool_a")
    reg.add(Category.READ_DB, "tool_b")
    reg.add(Category.READ_DB, "tool_c")
    assert reg.tools_in(Category.CORE) == ["tool_a"]
    assert sorted(reg.tools_in(Category.READ_DB)) == ["tool_b", "tool_c"]


def test_always_loaded_categories():
    assert Category.CORE.always_loaded is True
    assert Category.LAZY_META.always_loaded is True
    assert Category.AUDIT_BASICS.always_loaded is True
    assert Category.AUDIT_AUX.always_loaded is True
    assert Category.READ_DB.always_loaded is False  # auto-loaded after connect
    assert Category.WRITE_CORE.always_loaded is False  # on-demand
