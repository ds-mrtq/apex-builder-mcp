# src/apex_builder_mcp/connection/auth_mode.py
"""Auth mode selector — SQLcl saved-conn (primary) or password (fallback)."""
from __future__ import annotations

from enum import StrEnum

from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
from apex_builder_mcp.schema.profile import Profile


class AuthMode(StrEnum):
    SQLCL = "sqlcl"
    PASSWORD = "password"


class AuthResolutionError(RuntimeError):
    """Raised when auth resolution fails (e.g., SQLcl conn unreachable)."""


def resolve_auth_mode(profile: Profile) -> AuthMode:
    return AuthMode(profile.auth_mode)


def verify_sqlcl_connection(conn_name: str) -> bool:
    """Confirm `sql -name <conn>` connects + executes a trivial query."""
    sql = "set heading off feedback off pagesize 0\nselect 'OK_CHECK' from dual;\nexit\n"
    result = run_sqlcl(conn_name, sql, timeout=30)
    if result.rc != 0:
        raise AuthResolutionError(
            f"sql -name {conn_name} returned rc={result.rc}: {result.cleaned}"
        )
    if "OK_CHECK" not in result.stdout:
        raise AuthResolutionError(
            f"sql -name {conn_name} did not return OK_CHECK marker:\n{result.cleaned}"
        )
    return True
