# tests/unit/test_sql_guard.py
from __future__ import annotations

import pytest

from apex_builder_mcp.apex_api.sql_guard import (
    SqlGuardError,
    is_safe_select,
    validate_object_name,
)


def test_safe_select():
    assert is_safe_select("select * from emp") is True
    assert is_safe_select("SELECT a, b FROM t WHERE x = :p") is True
    assert is_safe_select("with cte as (select 1 from dual) select * from cte") is True


def test_reject_semicolon_chain():
    with pytest.raises(SqlGuardError, match="semicolon"):
        is_safe_select("select 1 from dual; drop table emp;", raise_on_fail=True)


def test_reject_ddl():
    with pytest.raises(SqlGuardError, match="DDL"):
        is_safe_select("create table x (a number)", raise_on_fail=True)
    with pytest.raises(SqlGuardError, match="DDL"):
        is_safe_select("drop table emp", raise_on_fail=True)
    with pytest.raises(SqlGuardError, match="DDL"):
        is_safe_select("alter table x add b number", raise_on_fail=True)


def test_reject_dml():
    for stmt in [
        "insert into x values(1)",
        "update x set a=1",
        "delete from x",
        "merge into x using y on (1=1) when matched then update set a=1",
    ]:
        with pytest.raises(SqlGuardError, match="DML"):
            is_safe_select(stmt, raise_on_fail=True)


def test_reject_plsql_block():
    with pytest.raises(SqlGuardError, match="PLSQL"):
        is_safe_select("begin null; end;", raise_on_fail=True)
    with pytest.raises(SqlGuardError, match="PLSQL"):
        is_safe_select("declare x number; begin null; end;", raise_on_fail=True)


def test_reject_db_link():
    with pytest.raises(SqlGuardError, match="db link"):
        is_safe_select("select * from emp@remote", raise_on_fail=True)


def test_reject_comment_exit_tricks():
    # Single-line comment cannot hide a semicolon-chained DDL because we check
    # AFTER stripping comments
    with pytest.raises(SqlGuardError):
        is_safe_select("select * from emp -- ; drop table x", raise_on_fail=True)


def test_validate_object_name_accepts_apex_views():
    assert validate_object_name("APEX_APPLICATIONS") is True
    assert validate_object_name("apex_applications") is True
    assert validate_object_name("EMP") is True


def test_validate_object_name_rejects_quoted_or_bad_chars():
    with pytest.raises(SqlGuardError):
        validate_object_name("emp; drop", raise_on_fail=True)
    with pytest.raises(SqlGuardError):
        validate_object_name('"weird name"', raise_on_fail=True)
    with pytest.raises(SqlGuardError):
        validate_object_name("emp@remote", raise_on_fail=True)
