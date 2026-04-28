# tests/unit/test_policy.py
from __future__ import annotations

import pytest

from apex_builder_mcp.guard.policy import (
    PolicyContext,
    PolicyResult,
    enforce_policy,
)
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile

# Reference imported symbol so tooling sees it as used (it documents the API surface).
_ = PolicyResult


def make_ctx(env="DEV", destructive=False, **kw):
    profile = Profile(
        sqlcl_name="X",
        environment=env,
        workspace="W",
        block_destructive=kw.get("block_destructive", env == "PROD"),
    )
    return PolicyContext(
        profile=profile,
        tool_name="apex_add_page",
        is_destructive=destructive,
    )


def test_dev_returns_execute():
    r = enforce_policy(make_ctx("DEV"))
    assert r.decision_name == "EXECUTE"
    assert r.proceed_live is True


def test_test_returns_dry_run_only():
    r = enforce_policy(make_ctx("TEST"))
    assert r.decision_name == "DRY_RUN_ONLY"
    assert r.proceed_live is False


def test_prod_raises():
    with pytest.raises(ApexBuilderError) as exc_info:
        enforce_policy(make_ctx("PROD"))
    assert exc_info.value.code == "ENV_GUARD_PROD_REJECTED"
    assert "manual App Builder pipeline" in exc_info.value.suggestion.lower() or \
        "manual app builder pipeline" in exc_info.value.suggestion.lower()


def test_destructive_in_dev_with_block_raises():
    ctx = make_ctx("DEV", destructive=True, block_destructive=True)
    with pytest.raises(ApexBuilderError) as exc_info:
        enforce_policy(ctx)
    assert exc_info.value.code == "ENV_GUARD_DESTRUCTIVE_BLOCKED"
