# tests/unit/test_tools_connection.py
from __future__ import annotations

from apex_builder_mcp.tools.connection import apex_list_profiles


def test_list_profiles_returns_dict(tmp_profiles_yaml, monkeypatch):
    monkeypatch.setattr(
        "apex_builder_mcp.tools.connection.PROFILES_YAML",
        tmp_profiles_yaml,
    )
    result = apex_list_profiles()
    assert "DEV1" in result
    assert "TEST1" in result
    assert "PROD" in result
    assert result["DEV1"]["environment"] == "DEV"
    # Important: no password field surfaced
    assert "password" not in result["DEV1"]
