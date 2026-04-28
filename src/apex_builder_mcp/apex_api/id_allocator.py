# src/apex_builder_mcp/apex_api/id_allocator.py
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def pick_free_id(used: set[int], min_id: int = 1) -> int:
    """Return the smallest free id >= min_id that is not in `used`."""
    candidate = min_id
    while candidate in used:
        candidate += 1
    return candidate


def query_used_page_ids(connection: Any, app_id: int) -> set[int]:
    cur = connection.cursor()
    cur.execute(
        "select page_id from apex_application_pages where application_id = :app_id",
        app_id=app_id,
    )
    return {row[0] for row in cur.fetchall()}


def query_used_region_ids(connection: Any, app_id: int, page_id: int) -> set[int]:
    cur = connection.cursor()
    cur.execute(
        """
        select region_id
          from apex_application_page_regions
         where application_id = :app_id and page_id = :page_id
        """,
        app_id=app_id,
        page_id=page_id,
    )
    return {row[0] for row in cur.fetchall()}


def query_used_item_ids(connection: Any, app_id: int, page_id: int) -> set[int]:
    cur = connection.cursor()
    cur.execute(
        """
        select item_id
          from apex_application_page_items
         where application_id = :app_id and page_id = :page_id
        """,
        app_id=app_id,
        page_id=page_id,
    )
    return {row[0] for row in cur.fetchall()}


@contextmanager
def app_lock(connection: Any, app_id: int, timeout_sec: int = 30) -> Iterator[None]:
    """Acquire DBMS_LOCK named 'apex-builder:app:{app_id}' for the duration of the context."""
    lock_name = f"apex-builder:app:{app_id}"
    cur = connection.cursor()
    handle = cur.var(str)
    cur.callproc("dbms_lock.allocate_unique", [lock_name, handle])
    handle_value = handle.getvalue()
    result = cur.var(int)
    cur.callproc(
        "dbms_lock.request",
        [handle_value, 6, timeout_sec, True, result],  # 6 = X_MODE (exclusive)
    )
    if result.getvalue() not in (0, 4):  # 0=success, 4=already own
        raise RuntimeError(
            f"DBMS_LOCK.REQUEST returned {result.getvalue()} for {lock_name}"
        )
    try:
        yield
    finally:
        cur.callproc("dbms_lock.release", [handle_value])
