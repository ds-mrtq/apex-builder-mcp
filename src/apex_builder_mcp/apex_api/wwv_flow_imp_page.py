"""Minimal Phase 0 stubs around WWV_FLOW_IMP_PAGE for Gate 2.

WARNING: WWV_FLOW_IMP_PAGE is an internal APEX package, NOT in the public API
reference. These stubs exist solely to verify oracledb thin mode can call them.
Phase 0 round-trip proof gate (Task 41) determines whether we trust these
calls for MVP. Plan 2A will replace these stubs with verified wrappers.
"""
from __future__ import annotations

from typing import Any


def call_create_page(connection: Any, **kw: Any) -> None:
    """Thin pass-through to wwv_flow_imp_page.create_page. NO id_allocator,
    NO ALL_ARGUMENTS verify. Use only for Gate 2 verification."""
    cur = connection.cursor()
    cur.callproc("wwv_flow_imp_page.create_page", keyword_parameters=kw)


def call_create_region(connection: Any, **kw: Any) -> None:
    cur = connection.cursor()
    cur.callproc("wwv_flow_imp_page.create_page_plug", keyword_parameters=kw)


def call_create_item(connection: Any, **kw: Any) -> None:
    cur = connection.cursor()
    cur.callproc("wwv_flow_imp_page.create_page_item", keyword_parameters=kw)


def call_create_button(connection: Any, **kw: Any) -> None:
    cur = connection.cursor()
    cur.callproc("wwv_flow_imp_page.create_page_button", keyword_parameters=kw)


def call_create_process(connection: Any, **kw: Any) -> None:
    cur = connection.cursor()
    cur.callproc("wwv_flow_imp_page.create_page_process", keyword_parameters=kw)
