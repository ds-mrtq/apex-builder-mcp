# src/apex_builder_mcp/tools/audit.py
from __future__ import annotations

from dataclasses import asdict
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
