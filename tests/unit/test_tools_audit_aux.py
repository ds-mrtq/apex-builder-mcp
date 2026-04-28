# tests/unit/test_tools_audit_aux.py
from __future__ import annotations

from unittest.mock import MagicMock

from apex_builder_mcp.audit.log import AuditEntry, AuditLogWriter
from apex_builder_mcp.tools.audit import apex_emergency_stop, apex_get_audit_log


def test_get_audit_log_returns_recent_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("apex_builder_mcp.tools.audit.AUDIT_DIR", tmp_path)
    writer = AuditLogWriter(audit_dir=tmp_path)
    for i in range(3):
        writer.append(
            "DEV1",
            AuditEntry(tool="apex_x", profile="DEV1", env="DEV", params={"i": i}, result="ok"),
        )
    result = apex_get_audit_log(profile="DEV1", limit=2)
    assert len(result["entries"]) == 2


def test_emergency_stop_disconnects_and_freezes(monkeypatch):
    fake_pool = MagicMock()
    monkeypatch.setattr("apex_builder_mcp.tools.audit._get_pool", lambda: fake_pool)
    result = apex_emergency_stop(reason="test panic")
    fake_pool.disconnect.assert_called_once()
    assert result["frozen"] is True
    assert result["reason"] == "test panic"
