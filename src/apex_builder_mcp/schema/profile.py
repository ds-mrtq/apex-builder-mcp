# src/apex_builder_mcp/schema/profile.py
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Profile(BaseModel):
    sqlcl_name: str = Field(min_length=1)
    environment: Literal["DEV", "TEST", "PROD"]
    workspace: str = Field(min_length=1)
    default_app_id: int | None = None
    auto_export_dir: Path | None = None
    require_dry_run: bool = False
    require_explicit_apply: bool = False
    block_destructive: bool = False
    snapshot_acl_before_write: bool = False
