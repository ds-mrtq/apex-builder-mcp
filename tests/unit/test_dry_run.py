# tests/unit/test_dry_run.py
from __future__ import annotations

from apex_builder_mcp.guard.dry_run import render_plsql_call


def test_render_simple_call():
    sql = render_plsql_call(
        proc_name="wwv_flow_imp_page.create_page",
        params={"p_id": 5, "p_name": "Sales"},
    )
    assert "wwv_flow_imp_page.create_page" in sql
    assert "p_id => 5" in sql
    assert "p_name => 'Sales'" in sql


def test_render_with_real_bool():
    sql = render_plsql_call(
        proc_name="x.y",
        params={"p_use_as_row_header": False, "p_filter_exact_match": True},
    )
    # Real PL/SQL booleans, NOT quoted
    assert "p_use_as_row_header => false" in sql
    assert "'false'" not in sql
    assert "p_filter_exact_match => true" in sql


def test_render_with_none_as_null():
    sql = render_plsql_call(proc_name="x.y", params={"p_optional": None})
    assert "p_optional => null" in sql


def test_render_with_int_and_string_mix():
    sql = render_plsql_call(
        proc_name="x.y",
        params={"p_id": 5, "p_text": "hello", "p_flag": True},
    )
    assert "p_id => 5" in sql
    assert "p_text => 'hello'" in sql
    assert "p_flag => true" in sql


def test_string_with_apostrophe_escaped():
    sql = render_plsql_call(proc_name="x.y", params={"p_name": "O'Brien"})
    assert "'O''Brien'" in sql
