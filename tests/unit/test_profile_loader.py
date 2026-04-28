# tests/unit/test_profile_loader.py
from __future__ import annotations

import pytest

from apex_builder_mcp.connection.profile import (
    ProfileNotFoundError,
    load_profile,
    load_profiles,
)


def test_load_profiles_yaml(tmp_profiles_yaml):
    profiles = load_profiles(tmp_profiles_yaml)
    assert "DEV1" in profiles
    assert "PROD" in profiles
    assert profiles["DEV1"].environment == "DEV"
    assert profiles["PROD"].block_destructive is True


def test_load_profile_by_name(tmp_profiles_yaml):
    p = load_profile("DEV1", tmp_profiles_yaml)
    assert p.sqlcl_name == "HTC_DEV1"


def test_load_missing_profile_raises(tmp_profiles_yaml):
    with pytest.raises(ProfileNotFoundError):
        load_profile("NOPE", tmp_profiles_yaml)


def test_load_profiles_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profiles(tmp_path / "missing.yaml")
