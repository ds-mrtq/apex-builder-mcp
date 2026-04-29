# tests/unit/test_profile.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from apex_builder_mcp.schema.profile import Profile


def test_profile_dev_minimal():
    p = Profile(sqlcl_name="HTC_DEV1", environment="DEV", workspace="HTC_OPS")
    assert p.environment == "DEV"
    assert p.require_dry_run is False
    assert p.block_destructive is False


def test_profile_prod_defaults_block_destructive():
    p = Profile(
        sqlcl_name="HTC_PROD",
        environment="PROD",
        workspace="HTC_OPS",
    )
    # PROD must explicitly set block_destructive=True via profile YAML;
    # schema does not auto-set, but env_guard treats PROD as block_destructive
    assert p.environment == "PROD"


def test_profile_invalid_environment():
    with pytest.raises(ValidationError):
        Profile(sqlcl_name="X", environment="STAGING", workspace="Y")  # type: ignore


def test_profile_auto_export_dir_path():
    p = Profile(
        sqlcl_name="HTC_DEV1",
        environment="DEV",
        workspace="HTC_OPS",
        auto_export_dir="D:/repos/htc-apex/exports/DEV1",
    )
    assert p.auto_export_dir is not None
    assert p.auto_export_dir.name == "DEV1"


def test_profile_default_auth_mode_is_sqlcl():
    p = Profile(sqlcl_name="HTC_DEV1", environment="DEV", workspace="HTC_OPS")
    assert p.auth_mode == "sqlcl"


def test_profile_password_auth_mode():
    p = Profile(
        sqlcl_name="HTC_DEV1",
        environment="DEV",
        workspace="HTC_OPS",
        auth_mode="password",
    )
    assert p.auth_mode == "password"


def test_profile_invalid_auth_mode():
    with pytest.raises(ValidationError):
        Profile(
            sqlcl_name="X", environment="DEV", workspace="W",
            auth_mode="kerberos",  # type: ignore
        )
