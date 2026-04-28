# tests/unit/test_env_guard.py
from __future__ import annotations

import pytest

from apex_builder_mcp.guard.env_guard import (
    EnvGuardError,
    PolicyDecision,
    decide_write_action,
)


def test_dev_allows_write():
    d = decide_write_action(environment="DEV", tool_name="apex_add_page", is_destructive=False)
    assert d == PolicyDecision.EXECUTE


def test_test_forces_dry_run():
    d = decide_write_action(environment="TEST", tool_name="apex_add_page", is_destructive=False)
    assert d == PolicyDecision.DRY_RUN_ONLY


def test_prod_rejects_write():
    d = decide_write_action(environment="PROD", tool_name="apex_add_page", is_destructive=False)
    assert d == PolicyDecision.REJECT


def test_destructive_blocked_in_prod():
    d = decide_write_action(environment="PROD", tool_name="apex_delete_page", is_destructive=True)
    assert d == PolicyDecision.REJECT


def test_destructive_in_dev_with_block_flag():
    d = decide_write_action(
        environment="DEV",
        tool_name="apex_delete_page",
        is_destructive=True,
        block_destructive=True,
    )
    assert d == PolicyDecision.REJECT


def test_destructive_in_dev_without_block_flag():
    d = decide_write_action(
        environment="DEV",
        tool_name="apex_delete_page",
        is_destructive=True,
        block_destructive=False,
    )
    assert d == PolicyDecision.EXECUTE


def test_unknown_env_raises():
    with pytest.raises(EnvGuardError):
        decide_write_action(environment="STAGING", tool_name="x", is_destructive=False)  # type: ignore
