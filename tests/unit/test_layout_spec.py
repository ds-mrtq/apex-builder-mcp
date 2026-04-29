from __future__ import annotations

import pytest
from pydantic import ValidationError

from apex_builder_mcp.schema.layout_spec import (
    GridSpec,
    ItemSpec,
    LayoutSpec,
    RegionSpec,
)


def test_grid_spec_valid():
    g = GridSpec(col_span=6)
    assert g.col_span == 6


def test_grid_spec_rejects_out_of_range():
    with pytest.raises(ValidationError):
        GridSpec(col_span=0)
    with pytest.raises(ValidationError):
        GridSpec(col_span=13)


def test_item_spec_basic():
    i = ItemSpec(name="P1_X", type="TEXT", label="X label")
    assert i.type == "TEXT"


def test_item_spec_rejects_empty_name():
    with pytest.raises(ValidationError):
        ItemSpec(name="", type="TEXT")


def test_item_spec_rejects_invalid_type():
    with pytest.raises(ValidationError):
        ItemSpec(name="P1_X", type="WIDGET")  # type: ignore


def test_region_spec_with_items():
    r = RegionSpec(
        name="hero",
        template="t-Hero",
        grid=GridSpec(col_span=12),
        items=[ItemSpec(name="P1_X", type="TEXT")],
    )
    assert len(r.items) == 1


def test_region_rejects_invalid_type():
    with pytest.raises(ValidationError):
        RegionSpec(
            name="x",
            template="t",
            grid=GridSpec(col_span=12),
            type="badtype",  # type: ignore
        )


def test_region_rejects_invalid_position():
    with pytest.raises(ValidationError):
        RegionSpec(
            name="x",
            template="t",
            grid=GridSpec(col_span=12),
            position="MIDDLE",  # type: ignore
        )


def test_layout_spec_full():
    spec = LayoutSpec(
        app_id=110,
        page_id=5,
        regions=[
            RegionSpec(
                name="r1",
                template="t-Region",
                grid=GridSpec(col_span=12),
            ),
        ],
    )
    assert spec.app_id == 110
    assert len(spec.regions) == 1


def test_layout_spec_requires_at_least_one_region():
    with pytest.raises(ValidationError):
        LayoutSpec(app_id=110, page_id=5, regions=[])


def test_layout_spec_rejects_invalid_app_id():
    with pytest.raises(ValidationError):
        LayoutSpec(
            app_id=0,
            page_id=5,
            regions=[
                RegionSpec(
                    name="r1",
                    template="t",
                    grid=GridSpec(col_span=12),
                ),
            ],
        )
