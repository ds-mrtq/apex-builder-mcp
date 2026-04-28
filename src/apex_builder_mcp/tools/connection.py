# src/apex_builder_mcp/tools/connection.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml

from apex_builder_mcp.connection.credential import set_password
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


@apex_tool(name="apex_setup_profile", category=Category.CORE)
def apex_setup_profile(
    name: str,
    sqlcl_name: str,
    environment: Literal["DEV", "TEST", "PROD"],
    workspace: str,
    password: str,
    default_app_id: int | None = None,
    auto_export_dir: str | None = None,
    require_dry_run: bool = False,
    block_destructive: bool = False,
) -> dict[str, Any]:
    """Create or update a profile + store password in keyring. YAML never holds password."""
    PROFILES_YAML.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any]
    if PROFILES_YAML.exists():
        raw = yaml.safe_load(PROFILES_YAML.read_text(encoding="utf-8")) or {}
    else:
        raw = {}
    raw.setdefault("profiles", {})
    raw["profiles"][name] = {
        "sqlcl_name": sqlcl_name,
        "environment": environment,
        "workspace": workspace,
        "default_app_id": default_app_id,
        "auto_export_dir": auto_export_dir,
        "require_dry_run": require_dry_run,
        "block_destructive": block_destructive,
    }
    PROFILES_YAML.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    set_password(name, password)
    return {"name": name, "saved": True}
