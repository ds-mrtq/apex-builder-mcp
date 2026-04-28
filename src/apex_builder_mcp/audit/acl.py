# src/apex_builder_mcp/audit/acl.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AclAssignment:
    user_name: str
    role_static_id: str


@dataclass
class AclSnapshot:
    app_id: int
    assignments: list[AclAssignment] = field(default_factory=list)


@dataclass
class AclDiff:
    added: list[AclAssignment]
    removed: list[AclAssignment]

    @property
    def empty(self) -> bool:
        return not self.added and not self.removed


def write_snapshot_yaml(snap: AclSnapshot, path: Path) -> None:
    raw: dict[str, Any] = {
        "app_id": snap.app_id,
        "assignments": [asdict(a) for a in snap.assignments],
    }
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def read_snapshot_yaml(path: Path) -> AclSnapshot:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AclSnapshot(
        app_id=raw["app_id"],
        assignments=[AclAssignment(**a) for a in raw["assignments"]],
    )


def diff_acl(snap: AclSnapshot, current: list[AclAssignment]) -> AclDiff:
    snap_set = set(snap.assignments)
    curr_set = set(current)
    return AclDiff(
        added=sorted(curr_set - snap_set, key=lambda a: (a.user_name, a.role_static_id)),
        removed=sorted(snap_set - curr_set, key=lambda a: (a.user_name, a.role_static_id)),
    )


def query_current_acl(connection: Any, app_id: int) -> list[AclAssignment]:
    cur = connection.cursor()
    cur.execute(
        """
        select user_name, role_static_id
          from apex_appl_acl_user_roles
         where application_id = :app_id
         order by upper(user_name), role_static_id
        """,
        app_id=app_id,
    )
    return [AclAssignment(user_name=u, role_static_id=r) for u, r in cur.fetchall()]


def restore_acl(connection: Any, snap: AclSnapshot) -> None:
    cur = connection.cursor()
    for a in snap.assignments:
        cur.callproc(
            "apex_acl.add_user_role",
            keyword_parameters={
                "p_application_id": snap.app_id,
                "p_user_name": a.user_name,
                "p_role_static_id": a.role_static_id,
            },
        )
    connection.commit()
