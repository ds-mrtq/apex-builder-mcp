# src/apex_builder_mcp/tools/connection.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from apex_builder_mcp.connection.profile import load_profiles
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool

PROFILES_YAML: Path = Path.home() / ".apex-builder-mcp" / "profiles.yaml"


@apex_tool(name="apex_list_profiles", category=Category.CORE)
def apex_list_profiles() -> dict[str, dict[str, Any]]:
    """List configured profiles. Does NOT expose passwords."""
    if not PROFILES_YAML.exists():
        return {}
    profiles = load_profiles(PROFILES_YAML)
    return {
        name: {
            "sqlcl_name": p.sqlcl_name,
            "environment": p.environment,
            "workspace": p.workspace,
            "default_app_id": p.default_app_id,
            "auto_export_dir": str(p.auto_export_dir) if p.auto_export_dir else None,
            "require_dry_run": p.require_dry_run,
            "block_destructive": p.block_destructive,
        }
        for name, p in profiles.items()
    }
