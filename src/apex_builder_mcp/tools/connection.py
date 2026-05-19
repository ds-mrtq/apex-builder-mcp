# src/apex_builder_mcp/tools/connection.py
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

import yaml

from apex_builder_mcp.connection.credential import get_password, set_password
from apex_builder_mcp.connection.pool import ApexBuilderPool
from apex_builder_mcp.connection.profile import load_profile, load_profiles
from apex_builder_mcp.connection.sqlcl_metadata import read_connection_metadata
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.tools.lazy import _get_loader as _get_lazy_loader

# Default overall budget for apex_connect (load profile + connmgr lookup + Oracle TCP connect).
# Override with env APEX_BUILDER_CONNECT_TIMEOUT_SEC (integer seconds, min 5).
DEFAULT_CONNECT_TIMEOUT_SEC = 60
_T = TypeVar("_T")


def _connect_timeout_sec() -> int:
    raw = os.environ.get("APEX_BUILDER_CONNECT_TIMEOUT_SEC")
    if raw:
        try:
            return max(5, int(raw))
        except ValueError:
            pass
    return DEFAULT_CONNECT_TIMEOUT_SEC


def _run_with_timeout(fn: Callable[[], _T], timeout: int) -> _T:
    """Run fn in a daemon thread, join up to timeout. Re-raises fn's exception.

    On timeout: raises TimeoutError. The worker thread is left running (daemon),
    not killed — Python has no safe way to interrupt blocking C calls (oracledb,
    socket). Daemon = process exit kills it.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:
            box["exc"] = e

    t = threading.Thread(target=target, daemon=True, name="apex-connect")
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError(f"operation did not complete within {timeout}s")
    if "exc" in box:
        raise box["exc"]
    return box["value"]

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
    """Connect to DB using a configured profile.

    Never prompts interactively — MCP stdio transport has no TTY, and a getpass
    read against a JSON-RPC pipe would block the server forever. If no password
    is stored in the OS credential store, raises CRED_MISSING with a pointer to
    apex_setup_profile.

    Wrapped in an overall budget (APEX_BUILDER_CONNECT_TIMEOUT_SEC, default 60s);
    on timeout the error names the stage that was running.
    """
    timeout = _connect_timeout_sec()
    stage: dict[str, str] = {"name": "init"}

    def body() -> dict[str, Any]:
        stage["name"] = "load_profile"
        profile = load_profile(profile_name, PROFILES_YAML)

        stage["name"] = "read_connection_metadata"
        md = read_connection_metadata(profile.sqlcl_name)

        stage["name"] = "get_password"
        password = get_password(profile_name, prompt_if_missing=False)
        if not password:
            raise ApexBuilderError(
                code="CRED_MISSING",
                message=f"No password stored for profile {profile_name!r}",
                suggestion=(
                    "Run apex_setup_profile to register this profile and its "
                    "password in the OS credential store before apex_connect."
                ),
            )

        stage["name"] = "oracledb_connect"
        pool = _get_or_create_pool()
        pool.connect(profile=profile, dsn=md.dsn, user=md.user, password=password)

        stage["name"] = "post_connect"
        state = get_state()
        state.set_profile(profile)
        state.mark_connected()
        loader = _get_lazy_loader()
        loader.on_post_connect()

        return {
            "state": state.status,
            "profile": profile_name,
            "environment": profile.environment,
            "workspace": profile.workspace,
            "user": md.user,
            "loaded_categories": sorted(c.value for c in loader.loaded_categories()),
        }

    try:
        return _run_with_timeout(body, timeout)
    except TimeoutError:
        raise ApexBuilderError(
            code="CONNECT_TIMEOUT",
            message=(
                f"apex_connect timed out after {timeout}s "
                f"while running stage {stage['name']!r}"
            ),
            suggestion=(
                "Increase APEX_BUILDER_CONNECT_TIMEOUT_SEC if the DB is "
                "expected to be slow, or verify network reachability and "
                "the SQLcl saved connection."
            ),
            metadata={"stage": stage["name"], "timeout_sec": timeout},
        ) from None


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
