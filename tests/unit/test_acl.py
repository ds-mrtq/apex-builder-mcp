# tests/unit/test_acl.py
from __future__ import annotations

from pathlib import Path

import yaml

from apex_builder_mcp.audit.acl import (
    AclAssignment,
    AclSnapshot,
    diff_acl,
    read_snapshot_yaml,
    write_snapshot_yaml,
)


def test_acl_snapshot_serializes_yaml(tmp_path: Path):
    snap = AclSnapshot(
        app_id=110,
        assignments=[
            AclAssignment(user_name="CONGNC", role_static_id="ADMIN"),
            AclAssignment(user_name="OPS_USER", role_static_id="OPERATOR"),
        ],
    )
    f = tmp_path / "snap.yaml"
    write_snapshot_yaml(snap, f)
    raw = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert raw["app_id"] == 110
    assert len(raw["assignments"]) == 2


def test_acl_round_trip(tmp_path: Path):
    snap = AclSnapshot(
        app_id=110,
        assignments=[AclAssignment(user_name="X", role_static_id="ADMIN")],
    )
    f = tmp_path / "snap.yaml"
    write_snapshot_yaml(snap, f)
    snap2 = read_snapshot_yaml(f)
    assert snap2.app_id == 110
    assert snap2.assignments[0].user_name == "X"


def test_diff_no_changes():
    snap = AclSnapshot(
        app_id=110,
        assignments=[AclAssignment(user_name="A", role_static_id="ADMIN")],
    )
    current = [AclAssignment(user_name="A", role_static_id="ADMIN")]
    d = diff_acl(snap, current)
    assert d.added == []
    assert d.removed == []


def test_diff_detects_removed():
    snap = AclSnapshot(
        app_id=110,
        assignments=[
            AclAssignment(user_name="A", role_static_id="ADMIN"),
            AclAssignment(user_name="B", role_static_id="OPERATOR"),
        ],
    )
    current = [AclAssignment(user_name="A", role_static_id="ADMIN")]
    d = diff_acl(snap, current)
    assert d.removed == [AclAssignment(user_name="B", role_static_id="OPERATOR")]


def test_diff_detects_added():
    snap = AclSnapshot(
        app_id=110,
        assignments=[AclAssignment(user_name="A", role_static_id="ADMIN")],
    )
    current = [
        AclAssignment(user_name="A", role_static_id="ADMIN"),
        AclAssignment(user_name="B", role_static_id="OPERATOR"),
    ]
    d = diff_acl(snap, current)
    assert d.added == [AclAssignment(user_name="B", role_static_id="OPERATOR")]
