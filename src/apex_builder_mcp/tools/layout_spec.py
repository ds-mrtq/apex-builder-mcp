"""apex_apply_layout_spec — bridge from LayoutSpec to add_region/add_item calls."""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.layout_spec import LayoutSpec
from apex_builder_mcp.tools.items import apex_add_item
from apex_builder_mcp.tools.regions import apex_add_region

_DISPLAY_AS_MAP = {
    "TEXT": "NATIVE_TEXT_FIELD",
    "TEXTAREA": "NATIVE_TEXTAREA",
    "DATE": "NATIVE_DATE_PICKER_APEX",
    "SELECT": "NATIVE_SELECT_LIST",
    "HIDDEN": "NATIVE_HIDDEN",
    "NUMBER": "NATIVE_NUMBER_FIELD",
    "CHECKBOX": "NATIVE_CHECKBOX",
}


@apex_tool(name="apex_apply_layout_spec", category=Category.BRIDGES)
def apex_apply_layout_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Apply a LayoutSpec by iterating regions and creating each + their items.

    Validates spec via Pydantic. Calls apex_add_region for each region in
    the spec, then apex_add_item for each item within. Region/item IDs are
    auto-allocated starting at 8100/8200 (caller doesn't specify them in
    LayoutSpec).
    """
    try:
        parsed = LayoutSpec(**spec)
    except Exception as e:
        raise ApexBuilderError(
            code="LAYOUT_SPEC_INVALID",
            message=f"LayoutSpec validation failed: {e}",
            suggestion="Check spec against schema/layout_spec.py",
        ) from e

    next_region_id = 8100
    next_item_id = 8200
    region_results: list[dict[str, Any]] = []
    item_results: list[dict[str, Any]] = []

    for region in parsed.regions:
        region_result = apex_add_region(
            app_id=parsed.app_id,
            page_id=parsed.page_id,
            region_id=next_region_id,
            name=region.name,
            template_id=0,
            display_sequence=10 + 10 * len(region_results),
        )
        region_results.append(region_result)
        for item in region.items:
            display_as = _DISPLAY_AS_MAP.get(item.type, "NATIVE_TEXT_FIELD")
            item_result = apex_add_item(
                app_id=parsed.app_id,
                page_id=parsed.page_id,
                item_id=next_item_id,
                region_id=next_region_id,
                name=item.name,
                display_as=display_as,
                display_sequence=10 + 10 * len(item_results),
            )
            item_results.append(item_result)
            next_item_id += 1
        next_region_id += 1

    return {
        "app_id": parsed.app_id,
        "page_id": parsed.page_id,
        "regions_added": len(region_results),
        "items_added": len(item_results),
        "regions": region_results,
        "items": item_results,
    }
