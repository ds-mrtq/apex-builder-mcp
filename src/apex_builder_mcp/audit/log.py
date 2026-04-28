# src/apex_builder_mcp/audit/log.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class AuditEntry:
    tool: str
    profile: str
    env: str
    params: dict[str, Any]
    result: str
    sql_executed: str | None = None
    sql_preview: str | None = None
    dry_run: bool = False
    duration_ms: int | None = None
    new_ids: dict[str, int] = field(default_factory=dict)
    reject_reason: str | None = None
    suggestion: str | None = None
    auto_exported: bool = False
    export_path: str | None = None
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AuditLogWriter:
    def __init__(self, audit_dir: Path) -> None:
        self.audit_dir = audit_dir
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def append(self, profile_name: str, entry: AuditEntry) -> None:
        prof_dir = self.audit_dir / profile_name
        prof_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        f = prof_dir / f"{date_str}.jsonl"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
