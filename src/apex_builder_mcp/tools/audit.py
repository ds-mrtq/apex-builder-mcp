# src/apex_builder_mcp/tools/audit.py
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apex_builder_mcp.audit.acl import (
    AclSnapshot,
    diff_acl,
    query_current_acl,
    read_snapshot_yaml,
    restore_acl,
    write_snapshot_yaml,
)
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool

AUDIT_DIR: Path = Path.home() / ".apex-builder-mcp" / "audit"

# Module-level frozen flag tracking emergency-stop state per session.
_FROZEN: dict[str, str] = {}


def _get_pool() -> Any:
    from apex_builder_mcp.tools.connection import _get_or_create_pool
    return _get_or_create_pool()


@apex_tool(name="apex_snapshot_acl", category=Category.AUDIT_BASICS)
def apex_snapshot_acl(app_id: int, output_path: str) -> dict[str, Any]:
    pool = _get_pool()
    with pool.acquire() as conn:
        assignments = query_current_acl(conn, app_id)
    snap = AclSnapshot(app_id=app_id, assignments=assignments)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_snapshot_yaml(snap, out)
    return {"path": str(out), "count": len(assignments)}


@apex_tool(name="apex_restore_acl", category=Category.AUDIT_BASICS)
def apex_restore_acl(snapshot_path: str) -> dict[str, Any]:
    snap = read_snapshot_yaml(Path(snapshot_path))
    pool = _get_pool()
    with pool.acquire() as conn:
        restore_acl(conn, snap)
    return {"restored": len(snap.assignments), "app_id": snap.app_id}


@apex_tool(name="apex_diff_acl", category=Category.AUDIT_BASICS)
def apex_diff_acl(snapshot_path: str) -> dict[str, Any]:
    snap = read_snapshot_yaml(Path(snapshot_path))
    pool = _get_pool()
    with pool.acquire() as conn:
        current = query_current_acl(conn, snap.app_id)
    d = diff_acl(snap, current)
    return {
        "added": [asdict(a) for a in d.added],
        "removed": [asdict(a) for a in d.removed],
        "empty": d.empty,
    }


@apex_tool(name="apex_get_audit_log", category=Category.AUDIT_AUX)
def apex_get_audit_log(profile: str, limit: int = 50) -> dict[str, Any]:
    """Read most recent audit entries for a profile. Latest first."""
    prof_dir = AUDIT_DIR / profile
    if not prof_dir.exists():
        return {"entries": [], "profile": profile}
    files = sorted(prof_dir.glob("*.jsonl"), reverse=True)
    entries: list[dict[str, Any]] = []
    for f in files:
        for line in reversed(f.read_text(encoding="utf-8").strip().split("\n")):
            if line.strip():
                entries.append(json.loads(line))
                if len(entries) >= limit:
                    return {"entries": entries, "profile": profile}
    return {"entries": entries, "profile": profile}


@apex_tool(name="apex_emergency_stop", category=Category.AUDIT_AUX)
def apex_emergency_stop(reason: str) -> dict[str, Any]:
    """Disconnect pool, freeze MCP for rest of session, record reason."""
    pool = _get_pool()
    pool.disconnect()
    _FROZEN["reason"] = reason
    _FROZEN["ts"] = datetime.now(UTC).isoformat()
    return {"frozen": True, "reason": reason, "ts": _FROZEN["ts"]}


def is_frozen() -> bool:
    return "reason" in _FROZEN


def _reset_frozen_for_tests() -> None:
    """Test-only: clear frozen state."""
    _FROZEN.clear()
