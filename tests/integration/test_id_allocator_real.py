# tests/integration/test_id_allocator_real.py
from __future__ import annotations

import os

import pytest

from apex_builder_mcp.apex_api.id_allocator import app_lock
from apex_builder_mcp.connection.pool import ApexBuilderPool
from apex_builder_mcp.schema.profile import Profile

pytestmark = pytest.mark.integration


def _real_creds():
    dsn = os.environ.get("APEX_TEST_DSN")
    user = os.environ.get("APEX_TEST_USER")
    pw = os.environ.get("APEX_TEST_PASSWORD")
    if not all([dsn, user, pw]):
        pytest.skip("APEX_TEST_DSN/USER/PASSWORD env vars not set")
    return dsn, user, pw


def test_dbms_lock_acquire_release():
    dsn, user, pw = _real_creds()
    pool = ApexBuilderPool()
    pool.connect(
        profile=Profile(sqlcl_name="X", environment="DEV", workspace="W"),
        dsn=dsn, user=user, password=pw,
    )
    try:
        with pool.acquire() as conn:
            with app_lock(conn, app_id=999999, timeout_sec=5):
                pass  # got the lock; will release
    finally:
        pool.disconnect()
