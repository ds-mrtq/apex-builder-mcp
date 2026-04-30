"""Read-only DB inspection tools (auto-loaded after apex_connect).

All tools branch on ``profile.auth_mode`` via the shared helpers in
``tools/_read_helpers.py`` — including ``apex_run_sql``, which uses
SQLcl's CSV output format under ``auth_mode=sqlcl`` and the oracledb
pool under ``auth_mode=password``.
"""
from __future__ import annotations

import re
from typing import Any

from apex_builder_mcp.apex_api.sql_guard import is_safe_select, validate_object_name
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools._read_helpers import (
    query_dependencies,
    query_describe_table,
    query_get_source,
    query_list_tables,
    query_run_sql,
    query_search_objects,
)

MAX_ROWS = 10_000
ALLOWED_OBJECT_TYPES = {
    "PACKAGE", "PACKAGE BODY", "FUNCTION", "PROCEDURE",
    "VIEW", "TYPE", "TYPE BODY", "TRIGGER",
}

# Pattern for `apex_search_objects` LIKE-input:
# alphanumeric, _, $, # plus SQL LIKE wildcards (% and _).
_PATTERN_RE = re.compile(r"^[A-Za-z0-9_$#%]+$")


def _require_profile() -> Profile:
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    return state.profile


@apex_tool(name="apex_run_sql", category=Category.READ_DB)
def apex_run_sql(sql: str, max_rows: int = 1000) -> dict[str, Any]:
    """Execute read-only SELECT/WITH (no DDL/DML, no semicolon chains, no db links).

    Multi-layer guard: static syntax filter + max row cap. The least-privilege
    DB user (configured per scripts/grant_mcp_user.sql) provides additional
    Layer 1 defense - even if filter is bypassed, user has no DDL grants.

    Branches on ``profile.auth_mode``:
      * sqlcl  -> SQLcl subprocess with ``set sqlformat csv``, parsed via
        the stdlib ``csv`` module.
      * password -> oracledb pool (existing behavior).
    """
    is_safe_select(sql, raise_on_fail=True)
    if max_rows > MAX_ROWS:
        max_rows = MAX_ROWS
    profile = _require_profile()
    return query_run_sql(profile, sql, max_rows)


@apex_tool(name="apex_list_tables", category=Category.READ_DB)
def apex_list_tables(schema: str | None = None) -> dict[str, Any]:
    """List tables in current schema (or specified schema)."""
    if schema is not None:
        validate_object_name(schema, raise_on_fail=True)
    profile = _require_profile()
    rows = query_list_tables(profile, schema)
    return {"tables": rows, "count": len(rows)}


@apex_tool(name="apex_describe_table", category=Category.READ_DB)
def apex_describe_table(table_name: str, schema: str | None = None) -> dict[str, Any]:
    """Describe table columns."""
    validate_object_name(table_name, raise_on_fail=True)
    if schema is not None:
        validate_object_name(schema, raise_on_fail=True)
    profile = _require_profile()
    cols = query_describe_table(profile, table_name, schema)
    return {"table_name": table_name.upper(), "columns": cols}


@apex_tool(name="apex_get_source", category=Category.READ_DB)
def apex_get_source(
    object_name: str,
    object_type: str,
    schema: str | None = None,
) -> dict[str, Any]:
    """Get PL/SQL source for package/function/procedure/view/etc."""
    validate_object_name(object_name, raise_on_fail=True)
    if schema is not None:
        validate_object_name(schema, raise_on_fail=True)
    if object_type.upper() not in ALLOWED_OBJECT_TYPES:
        raise ValueError(
            f"object_type must be one of {sorted(ALLOWED_OBJECT_TYPES)}, got {object_type!r}"
        )
    profile = _require_profile()
    lines = query_get_source(profile, object_name, object_type, schema)
    return {
        "object_name": object_name.upper(),
        "object_type": object_type.upper(),
        "source": "".join(lines),
        "line_count": len(lines),
    }


@apex_tool(name="apex_search_objects", category=Category.READ_DB)
def apex_search_objects(
    pattern: str,
    object_types: list[str] | None = None,
) -> dict[str, Any]:
    """Search Oracle objects by name pattern (SQL LIKE), optionally filtered by type.

    Searches all_objects across the schemas the connected user can see.
    Pattern accepts alphanumeric, _, $, #, and SQL LIKE wildcards (% and _).
    Pattern is bound as a parameter so SQL injection is impossible at the
    binding layer; the regex is an additional defense-in-depth check.

    object_types is an optional list to restrict to e.g. ['PACKAGE','VIEW'].
    Each type must pass the same restricted set as apex_get_source.
    """
    if not pattern or not _PATTERN_RE.match(pattern):
        raise ApexBuilderError(
            code="INVALID_PATTERN",
            message=(
                f"pattern must contain only [A-Za-z0-9_$#%], got {pattern!r}"
            ),
            suggestion="Use SQL LIKE wildcards (% and _) only",
        )
    types_upper: list[str] = []
    if object_types:
        for t in object_types:
            up = t.upper()
            if up not in ALLOWED_OBJECT_TYPES:
                raise ApexBuilderError(
                    code="INVALID_OBJECT_TYPE",
                    message=(
                        f"object_type {t!r} not in allow-list "
                        f"{sorted(ALLOWED_OBJECT_TYPES)}"
                    ),
                    suggestion=(
                        "Pass object_types like ['PACKAGE','FUNCTION','VIEW']."
                    ),
                )
            types_upper.append(up)

    profile = _require_profile()
    rows = query_search_objects(
        profile, pattern, types_upper or None, MAX_ROWS
    )
    return {
        "pattern": pattern,
        "object_types": types_upper or None,
        "objects": rows,
        "count": len(rows),
    }


@apex_tool(name="apex_dependencies", category=Category.READ_DB)
def apex_dependencies(
    object_name: str,
    object_type: str | None = None,
) -> dict[str, Any]:
    """Show object dependencies: what `object_name` uses, and what uses it.

    Reads from all_dependencies. Returns two lists:
      * `uses`: rows where this object is `name` (i.e. it depends on others)
      * `used_by`: rows where this object is `referenced_name` (i.e. others
        depend on it)
    """
    validate_object_name(object_name, raise_on_fail=True)
    obj_upper = object_name.upper()
    type_upper = object_type.upper() if object_type else None
    if type_upper is not None and type_upper not in ALLOWED_OBJECT_TYPES:
        raise ApexBuilderError(
            code="INVALID_OBJECT_TYPE",
            message=(
                f"object_type {object_type!r} not in allow-list "
                f"{sorted(ALLOWED_OBJECT_TYPES)}"
            ),
            suggestion=(
                "Pass object_type as one of PACKAGE, PACKAGE BODY, "
                "FUNCTION, PROCEDURE, VIEW, TYPE, TYPE BODY, TRIGGER."
            ),
        )
    profile = _require_profile()
    uses, used_by = query_dependencies(
        profile, obj_upper, type_upper, MAX_ROWS
    )
    return {
        "object_name": obj_upper,
        "object_type": type_upper,
        "uses": uses,
        "used_by": used_by,
        "uses_count": len(uses),
        "used_by_count": len(used_by),
    }
