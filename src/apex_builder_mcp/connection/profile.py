# src/apex_builder_mcp/connection/profile.py
from __future__ import annotations

from pathlib import Path

import yaml

from apex_builder_mcp.schema.profile import Profile


class ProfileNotFoundError(KeyError):
    """Raised when requested profile name is not in profiles.yaml."""


def load_profiles(yaml_path: Path) -> dict[str, Profile]:
    """Load all profiles from YAML file."""
    if not yaml_path.exists():
        raise FileNotFoundError(f"Profile file not found: {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not raw or "profiles" not in raw:
        return {}
    return {name: Profile(**data) for name, data in raw["profiles"].items()}


def load_profile(name: str, yaml_path: Path) -> Profile:
    """Load a single profile by name."""
    profiles = load_profiles(yaml_path)
    if name not in profiles:
        raise ProfileNotFoundError(name)
    return profiles[name]
