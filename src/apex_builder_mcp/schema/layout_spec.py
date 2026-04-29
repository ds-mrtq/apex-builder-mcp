"""Layout spec Pydantic models — for apex_apply_layout_spec bridge tool."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GridSpec(BaseModel):
    col_span: int = Field(ge=1, le=12)
    col_start: int | None = None
    new_row: bool = False


class ItemSpec(BaseModel):
    name: str = Field(min_length=1)
    type: Literal["TEXT", "SELECT", "DATE", "HIDDEN", "TEXTAREA", "NUMBER", "CHECKBOX"]
    label: str | None = None
    source: dict[str, Any] | None = None
    grid: GridSpec | None = None


class RegionSpec(BaseModel):
    name: str = Field(min_length=1)
    template: str = Field(min_length=1)
    position: Literal["BODY", "BODY_1", "BODY_2", "BODY_3", "RIGHT_SIDE_OF_PAGE"] = "BODY"
    grid: GridSpec
    type: Literal["html", "ir", "ig", "form", "chart", "cards", "calendar"] = "html"
    attrs: dict[str, Any] = Field(default_factory=dict)
    items: list[ItemSpec] = Field(default_factory=list)
    sql_query: str | None = None
    columns: list[str] | None = None


class LayoutSpec(BaseModel):
    app_id: int = Field(gt=0)
    page_id: int = Field(gt=0)
    page_template: str = "Standard"
    regions: list[RegionSpec] = Field(min_length=1)
