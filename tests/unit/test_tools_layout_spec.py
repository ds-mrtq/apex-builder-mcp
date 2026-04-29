from __future__ import annotations

import pytest

from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.layout_spec import GridSpec, ItemSpec, LayoutSpec, RegionSpec
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.layout_spec import apex_apply_layout_spec


@pytest.fixture(autouse=True)
def _reset():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


def _setup_state():
    state = get_state()
    state.set_profile(
        Profile(sqlcl_name="x", environment="DEV", workspace="EREPORT")
    )
    state.mark_connected()


def test_apply_layout_spec_iterates_regions_and_items(monkeypatch):
    _setup_state()
    add_region_calls: list[dict] = []
    add_item_calls: list[dict] = []

    def fake_add_region(**kw):
        add_region_calls.append(kw)
        return {"region_id": kw["region_id"], "ok": True}

    def fake_add_item(**kw):
        add_item_calls.append(kw)
        return {"item_id": kw["item_id"], "ok": True}

    monkeypatch.setattr(
        "apex_builder_mcp.tools.layout_spec.apex_add_region", fake_add_region
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.layout_spec.apex_add_item", fake_add_item
    )

    spec = LayoutSpec(
        app_id=100,
        page_id=8000,
        regions=[
            RegionSpec(
                name="r1",
                template="t-Region",
                grid=GridSpec(col_span=12),
                items=[
                    ItemSpec(name="P8000_X", type="TEXT"),
                    ItemSpec(name="P8000_Y", type="DATE"),
                ],
            ),
            RegionSpec(
                name="r2",
                template="t-Region",
                grid=GridSpec(col_span=6),
            ),
        ],
    )
    result = apex_apply_layout_spec(spec.model_dump())
    assert len(add_region_calls) == 2
    assert len(add_item_calls) == 2
    assert result["regions_added"] == 2
    assert result["items_added"] == 2


def test_apply_layout_spec_rejects_invalid_input():
    _setup_state()
    # missing required fields → wrapped as ApexBuilderError(LAYOUT_SPEC_INVALID)
    with pytest.raises(ApexBuilderError) as exc_info:
        apex_apply_layout_spec({"app_id": 100})
    assert exc_info.value.code == "LAYOUT_SPEC_INVALID"


def test_apply_layout_spec_propagates_add_region_failure(monkeypatch):
    _setup_state()
    def fake_add_region(**kw):
        raise ApexBuilderError(
            code="WRITE_EXEC_FAIL",
            message="region failed",
            suggestion="check",
        )

    monkeypatch.setattr(
        "apex_builder_mcp.tools.layout_spec.apex_add_region", fake_add_region
    )

    spec = LayoutSpec(
        app_id=100,
        page_id=8000,
        regions=[
            RegionSpec(name="r1", template="t", grid=GridSpec(col_span=12)),
        ],
    )
    with pytest.raises(ApexBuilderError):
        apex_apply_layout_spec(spec.model_dump())


def test_apply_layout_spec_id_allocation_increments(monkeypatch):
    """Verify region_id and item_id increment as expected."""
    _setup_state()
    region_ids: list[int] = []
    item_ids: list[int] = []

    def fake_add_region(**kw):
        region_ids.append(kw["region_id"])
        return {"region_id": kw["region_id"]}

    def fake_add_item(**kw):
        item_ids.append(kw["item_id"])
        return {"item_id": kw["item_id"]}

    monkeypatch.setattr(
        "apex_builder_mcp.tools.layout_spec.apex_add_region", fake_add_region
    )
    monkeypatch.setattr(
        "apex_builder_mcp.tools.layout_spec.apex_add_item", fake_add_item
    )

    spec = LayoutSpec(
        app_id=100,
        page_id=8000,
        regions=[
            RegionSpec(
                name="r1",
                template="t",
                grid=GridSpec(col_span=12),
                items=[ItemSpec(name="X", type="TEXT")],
            ),
            RegionSpec(
                name="r2",
                template="t",
                grid=GridSpec(col_span=12),
                items=[ItemSpec(name="Y", type="TEXT")],
            ),
        ],
    )
    apex_apply_layout_spec(spec.model_dump())
    # Each region gets a different id; same for items
    assert len(set(region_ids)) == 2
    assert len(set(item_ids)) == 2
