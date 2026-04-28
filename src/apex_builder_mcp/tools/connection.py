# src/apex_builder_mcp/tools/connection.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml

from apex_builder_mcp.connection.credential import get_password, set_password
from apex_builder_mcp.connection.pool import ApexBuilderPool
from apex_builder_mcp.connection.profile import load_profile, load_profiles
from apex_builder_mcp.connection.sqlcl_metadata import read_connection_metadata
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError

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


# Module-level pool reference (one per MCP session)
_POOL: ApexBuilderPool | None = None


def _get_or_create_pool() -> ApexBuilderPool:
    global _POOL
    if _POOL is None:
        _POOL = ApexBuilderPool()
    return _POOL


def _reset_pool_for_tests() -> None:
    """Test-only: clear module-level pool singleton."""
    global _POOL
    _POOL = None


@apex_tool(name="apex_connect", category=Category.CORE)
def apex_connect(profile_name: str) -> dict[str, Any]:
    """Connect to DB using a configured profile."""
    profile = load_profile(profile_name, PROFILES_YAML)
    md = read_connection_metadata(profile.sqlcl_name)
    password = get_password(profile_name, prompt_if_missing=True, save_after_prompt=True)
    if not password:
        raise ApexBuilderError(
            code="CRED_MISSING",
            message=f"No password for profile {profile_name}",
            suggestion="Run apex_setup_profile to set the password.",
        )

    pool = _get_or_create_pool()
    pool.connect(profile=profile, dsn=md.dsn, user=md.user, password=password)

    state = get_state()
    state.set_profile(profile)
    state.mark_connected()

    return {
        "state": state.status,
        "profile": profile_name,
        "environment": profile.environment,
        "workspace": profile.workspace,
        "user": md.user,
    }


@apex_tool(name="apex_disconnect", category=Category.CORE)
def apex_disconnect() -> dict[str, Any]:
    """Disconnect from DB and mark state DISCONNECTED."""
    pool = _get_or_create_pool()
    pool.disconnect()
    state = get_state()
    state.mark_disconnected()
    return {"state": state.status}


@apex_tool(name="apex_status", category=Category.CORE)
def apex_status() -> dict[str, Any]:
    """Return current connection state. Safe to call from any state."""
    state = get_state()
    pool = _get_or_create_pool()
    return {
        "state": state.status,
        "profile": state.profile.sqlcl_name if state.profile else None,
        "pool_connected": pool.is_connected,
    }
