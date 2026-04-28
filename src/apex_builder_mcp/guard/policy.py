# src/apex_builder_mcp/guard/policy.py
from __future__ import annotations

from dataclasses import dataclass

from apex_builder_mcp.guard.env_guard import PolicyDecision, decide_write_action
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile


@dataclass(frozen=True)
class PolicyContext:
    profile: Profile
    tool_name: str
    is_destructive: bool


@dataclass(frozen=True)
class PolicyResult:
    decision_name: str
    proceed_live: bool


def enforce_policy(ctx: PolicyContext) -> PolicyResult:
    decision = decide_write_action(
        environment=ctx.profile.environment,
        tool_name=ctx.tool_name,
        is_destructive=ctx.is_destructive,
        block_destructive=ctx.profile.block_destructive,
    )
    if decision == PolicyDecision.EXECUTE:
        return PolicyResult(decision_name="EXECUTE", proceed_live=True)
    if decision == PolicyDecision.DRY_RUN_ONLY:
        return PolicyResult(decision_name="DRY_RUN_ONLY", proceed_live=False)

    # REJECT
    if ctx.profile.environment == "PROD":
        raise ApexBuilderError(
            code="ENV_GUARD_PROD_REJECTED",
            message=(
                f"Tool '{ctx.tool_name}' rejected on PROD profile. "
                "Write tools are not available on PROD in MVP."
            ),
            suggestion=(
                "Use the manual App Builder pipeline: generate split-export from DEV "
                "via auto-export, review diff, then import via App Builder UI."
            ),
            metadata={"profile_env": "PROD", "tool": ctx.tool_name},
        )
    raise ApexBuilderError(
        code="ENV_GUARD_DESTRUCTIVE_BLOCKED",
        message=(
            f"Tool '{ctx.tool_name}' is destructive and the profile has block_destructive=true."
        ),
        suggestion="Set block_destructive=false on the profile if intentional.",
        metadata={"profile_env": ctx.profile.environment, "tool": ctx.tool_name},
    )
