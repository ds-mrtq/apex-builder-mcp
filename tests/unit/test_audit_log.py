# tests/unit/test_audit_log.py
from __future__ import annotations

import json
from pathlib import Path

from apex_builder_mcp.audit.log import AuditEntry, AuditLogWriter


def test_write_one_entry(tmp_path: Path):
    writer = AuditLogWriter(audit_dir=tmp_path)
    entry = AuditEntry(
        tool="apex_add_page",
        profile="DEV1",
        env="DEV",
        params={"app_id": 110, "page_id": 5},
        result="ok",
        sql_executed="begin x(); end;",
        duration_ms=234,
    )
    writer.append("DEV1", entry)

    files = list(tmp_path.rglob("*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["tool"] == "apex_add_page"
    assert parsed["env"] == "DEV"
    assert parsed["params"]["app_id"] == 110


def test_write_multiple_entries_same_day(tmp_path: Path):
    writer = AuditLogWriter(audit_dir=tmp_path)
    for i in range(3):
        writer.append(
            "DEV1",
            AuditEntry(tool="x", profile="DEV1", env="DEV", params={"i": i}, result="ok"),
        )
    files = list(tmp_path.rglob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3


def test_separate_dir_per_profile(tmp_path: Path):
    writer = AuditLogWriter(audit_dir=tmp_path)
    writer.append(
        "DEV1", AuditEntry(tool="x", profile="DEV1", env="DEV", params={}, result="ok")
    )
    writer.append(
        "PROD", AuditEntry(tool="y", profile="PROD", env="PROD", params={}, result="rejected")
    )
    assert (tmp_path / "DEV1").exists()
    assert (tmp_path / "PROD").exists()
