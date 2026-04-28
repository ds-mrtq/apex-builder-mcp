# tests/unit/test_tools_setup_profile.py
from __future__ import annotations

from unittest.mock import MagicMock

import yaml

from apex_builder_mcp.tools.connection import apex_setup_profile


def test_setup_writes_yaml_and_calls_credential(tmp_path, monkeypatch):
    yaml_path = tmp_path / "profiles.yaml"
    monkeypatch.setattr("apex_builder_mcp.tools.connection.PROFILES_YAML", yaml_path)

    mock_set = MagicMock()
    monkeypatch.setattr("apex_builder_mcp.tools.connection.set_password", mock_set)

    apex_setup_profile(
        name="DEV1",
        sqlcl_name="HTC_DEV1",
        environment="DEV",
        workspace="HTC_OPS",
        password="secret123",
    )

    assert yaml_path.exists()
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert raw["profiles"]["DEV1"]["sqlcl_name"] == "HTC_DEV1"
    assert "password" not in raw["profiles"]["DEV1"]
    mock_set.assert_called_once_with("DEV1", "secret123")


def test_setup_appends_to_existing_yaml(tmp_path, monkeypatch):
    yaml_path = tmp_path / "profiles.yaml"
    existing = {"profiles": {"OLD": {"sqlcl_name": "X", "environment": "DEV", "workspace": "W"}}}
    yaml_path.write_text(yaml.safe_dump(existing), encoding="utf-8")
    monkeypatch.setattr("apex_builder_mcp.tools.connection.PROFILES_YAML", yaml_path)
    monkeypatch.setattr("apex_builder_mcp.tools.connection.set_password", MagicMock())

    apex_setup_profile(
        name="NEW",
        sqlcl_name="HTC_DEV2",
        environment="DEV",
        workspace="HTC_OPS",
        password="x",
    )

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert "OLD" in raw["profiles"]
    assert "NEW" in raw["profiles"]
