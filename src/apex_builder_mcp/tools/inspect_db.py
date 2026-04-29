"""Read-only DB inspection tools (auto-loaded after apex_connect)."""
from __future__ import annotations

import re
from typing import Any

from apex_builder_mcp.apex_api.sql_guard import is_safe_select, validate_object_name
from apex_builder_mcp.connection.state import get_state
from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.tool_decorator import apex_tool
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.tools._read_helpers import (
    query_dependencies,
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


def _get_pool() -> Any:
    from apex_builder_mcp.tools.connection import _get_or_create_pool
    return _get_or_create_pool()


@apex_tool(name="apex_run_sql", category=Category.READ_DB)
def apex_run_sql(sql: str, max_rows: int = 1000) -> dict[str, Any]:
    """Execute read-only SELECT/WITH (no DDL/DML, no semicolon chains, no db links).

    Multi-layer guard: static syntax filter + max row cap. The least-privilege
    DB user (configured per scripts/grant_mcp_user.sql) provides additional
    Layer 1 defense - even if filter is bypassed, user has no DDL grants.
    """
    is_safe_select(sql, raise_on_fail=True)
    if max_rows > MAX_ROWS:
        max_rows = MAX_ROWS
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchmany(max_rows)]
    return {"columns": cols, "rows": rows, "row_count": len(rows)}


@apex_tool(name="apex_list_tables", category=Category.READ_DB)
def apex_list_tables(schema: str | None = None) -> dict[str, Any]:
    """List tables in current schema (or specified schema)."""
    if schema is not None:
        validate_object_name(schema, raise_on_fail=True)
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        if schema:
            cur.execute(
                "select table_name, num_rows, last_analyzed "
                "from all_tables where owner = :owner order by table_name",
                owner=schema.upper(),
            )
        else:
            cur.execute(
                "select table_name, num_rows, last_analyzed "
                "from user_tables order by table_name"
            )
        rows = [
            {
                "table_name": r[0],
                "num_rows": r[1],
                "last_analyzed": str(r[2]) if r[2] else None,
            }
            for r in cur.fetchall()
        ]
    return {"tables": rows, "count": len(rows)}


@apex_tool(name="apex_describe_table", category=Category.READ_DB)
def apex_describe_table(table_name: str, schema: str | None = None) -> dict[str, Any]:
    """Describe table columns."""
    validate_object_name(table_name, raise_on_fail=True)
    if schema is not None:
        validate_object_name(schema, raise_on_fail=True)
    pool = _get_pool()
    owner = schema.upper() if schema else None
    with pool.acquire() as conn:
        cur = conn.cursor()
        if owner:
            cur.execute(
                """
                select column_name, data_type, data_length, nullable, data_default
                  from all_tab_columns
                 where owner = :owner and table_name = :tn
                 order by column_id
                """,
                owner=owner, tn=table_name.upper(),
            )
        else:
            cur.execute(
                """
                select column_name, data_type, data_length, nullable, data_default
                  from user_tab_columns
                 where table_name = :tn
                 order by column_id
                """,
                tn=table_name.upper(),
            )
        cols = [
            {
                "name": r[0],
                "type": r[1],
                "length": r[2],
                "nullable": r[3] == "Y",
                "default": str(r[4]) if r[4] else None,
            }
            for r in cur.fetchall()
        ]
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
    pool = _get_pool()
    owner = schema.upper() if schema else None
    with pool.acquire() as conn:
        cur = conn.cursor()
        if owner:
            cur.execute(
                """
                select text from all_source
                 where owner = :owner and name = :n and type = :t
                 order by line
                """,
                owner=owner, n=object_name.upper(), t=object_type.upper(),
            )
        else:
            cur.execute(
                """
                select text from user_source
                 where name = :n and type = :t
                 order by line
                """,
                n=object_name.upper(), t=object_type.upper(),
            )
        lines = [r[0] for r in cur.fetchall()]
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

    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    rows = query_search_objects(
        state.profile, pattern, types_upper or None, MAX_ROWS
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
    state = get_state()
    if state.profile is None:
        raise ApexBuilderError(
            code="NOT_CONNECTED",
            message="No active profile",
            suggestion="Call apex_connect first",
        )
    uses, used_by = query_dependencies(
        state.profile, obj_upper, type_upper, MAX_ROWS
    )
    return {
        "object_name": obj_upper,
        "object_type": type_upper,
        "uses": uses,
        "used_by": used_by,
        "uses_count": len(uses),
        "used_by_count": len(used_by),
    }
