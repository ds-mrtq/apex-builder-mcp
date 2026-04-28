# tests/unit/test_tools_audit_acl.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from apex_builder_mcp.audit.acl import AclAssignment, AclSnapshot
from apex_builder_mcp.tools.audit import (
    apex_diff_acl,
    apex_restore_acl,  # noqa: F401  # imported to verify tool registration
    apex_snapshot_acl,
)


def test_snapshot_writes_yaml(tmp_path, monkeypatch):
    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr("apex_builder_mcp.tools.audit._get_pool", lambda: fake_pool)
    monkeypatch.setattr(
        "apex_builder_mcp.tools.audit.query_current_acl",
        lambda c, app_id: [AclAssignment(user_name="A", role_static_id="ADMIN")],
    )

    out = apex_snapshot_acl(app_id=110, output_path=str(tmp_path / "snap.yaml"))
    assert Path(out["path"]).exists()


def test_diff_returns_added_removed(tmp_path, monkeypatch):
    snap_path = tmp_path / "snap.yaml"
    from apex_builder_mcp.audit.acl import write_snapshot_yaml
    write_snapshot_yaml(
        AclSnapshot(app_id=110, assignments=[AclAssignment(user_name="A", role_static_id="ADMIN")]),
        snap_path,
    )

    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__enter__.return_value = fake_conn
    monkeypatch.setattr("apex_builder_mcp.tools.audit._get_pool", lambda: fake_pool)
    monkeypatch.setattr(
        "apex_builder_mcp.tools.audit.query_current_acl",
        lambda c, app_id: [AclAssignment(user_name="B", role_static_id="OPERATOR")],
    )

    result = apex_diff_acl(snapshot_path=str(snap_path))
    assert result["added"] == [{"user_name": "B", "role_static_id": "OPERATOR"}]
    assert result["removed"] == [{"user_name": "A", "role_static_id": "ADMIN"}]
