# src/apex_builder_mcp/apex_api/sql_guard.py
"""Multi-layer SQL injection guard - Layer 3 (static syntax filter).

Per spec section 5.4 + Phase 0 finding: sqlparse alone is NOT a security
boundary for Oracle. This module provides static syntax filtering as one
of FIVE layers. Other layers:
- Layer 1: least-privilege DB user (no DDL/DML grants)
- Layer 2: bind parameters only (oracledb cursor.execute with named binds)
- Layer 3: this module (static filter for run_sql input)
- Layer 4: DBMS_SQL.PARSE pre-execution validation (verifies statement type)
- Layer 5: generator allowlist source object (validate_object_name here)
"""
from __future__ import annotations

import re

# Object name pattern: unquoted, simple identifiers only (no quotes, no @, no .)
_OBJECT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,29}$")

_DDL_KEYWORDS = {"CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME", "GRANT", "REVOKE"}
_DML_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "MERGE"}
_PLSQL_KEYWORDS = {"BEGIN", "DECLARE", "EXECUTE"}


class SqlGuardError(ValueError):
    """Raised when SQL fails the guard checks."""


def _check(failing: bool, msg: str, *, raise_on_fail: bool) -> bool:
    if failing:
        if raise_on_fail:
            raise SqlGuardError(msg)
        return False
    return True


def is_safe_select(sql: str, *, raise_on_fail: bool = False) -> bool:
    """Layer 3 syntax filter for read-only SQL.

    Accepts: SELECT or WITH ... SELECT, no semicolon chains, no DDL/DML/PLSQL,
    no db links.
    """
    if not sql:
        return _check(True, "empty SQL", raise_on_fail=raise_on_fail)
    s = sql.strip()
    # Strip comments
    s_no_line_comments = re.sub(r"--[^\n]*", "", s)
    s_clean = re.sub(r"/\*.*?\*/", "", s_no_line_comments, flags=re.DOTALL)

    upper = s_clean.upper()
    tokens = re.findall(r"\b[A-Z_]+\b", upper)
    token_set = set(tokens)

    # No PLSQL blocks (check before semicolons since blocks contain them)
    if token_set & _PLSQL_KEYWORDS:
        return _check(
            True,
            f"PLSQL block keywords found: {token_set & _PLSQL_KEYWORDS}",
            raise_on_fail=raise_on_fail,
        )

    # No semicolon chains in the original (pre-stripped) string. A single
    # trailing semicolon is fine. Checking the original prevents tricks like
    # `select ... -- ; drop table x` from sneaking past after comment removal,
    # because Oracle clients/parsers may handle comments differently than we do.
    if ";" in s.rstrip().rstrip(";"):
        return _check(
            True,
            "semicolon-chained statements not allowed",
            raise_on_fail=raise_on_fail,
        )

    # No DDL
    if token_set & _DDL_KEYWORDS:
        return _check(
            True,
            f"DDL keywords found: {token_set & _DDL_KEYWORDS}",
            raise_on_fail=raise_on_fail,
        )
    # No non-SELECT DML
    if token_set & _DML_KEYWORDS:
        return _check(
            True,
            f"DML keywords found: {token_set & _DML_KEYWORDS}",
            raise_on_fail=raise_on_fail,
        )
    # Must start with SELECT or WITH
    first = (tokens[0] if tokens else "").upper()
    if first not in ("SELECT", "WITH"):
        return _check(
            True,
            f"statement must start with SELECT or WITH (got '{first}')",
            raise_on_fail=raise_on_fail,
        )
    # No db links
    if re.search(r"@[A-Za-z]", s_clean):
        return _check(
            True,
            "db link syntax (@) not allowed",
            raise_on_fail=raise_on_fail,
        )
    return True


def validate_object_name(name: str, *, raise_on_fail: bool = False) -> bool:
    """Layer 5 ingredient - only allow unquoted simple Oracle object names."""
    if not _OBJECT_NAME_RE.match(name):
        return _check(
            True,
            f"invalid object name '{name}' (must match {_OBJECT_NAME_RE.pattern})",
            raise_on_fail=raise_on_fail,
        )
    return True
