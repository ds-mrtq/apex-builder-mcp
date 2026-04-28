# tests/integration/test_pool_real.py
from __future__ import annotations

import os

import pytest

from apex_builder_mcp.connection.pool import ApexBuilderPool
from apex_builder_mcp.schema.profile import Profile

pytestmark = pytest.mark.integration


def _real_dsn():
    """Read from env vars set per-machine; skip if missing."""
    dsn = os.environ.get("APEX_TEST_DSN")
    user = os.environ.get("APEX_TEST_USER")
    pw = os.environ.get("APEX_TEST_PASSWORD")
    if not all([dsn, user, pw]):
        pytest.skip("APEX_TEST_DSN/USER/PASSWORD env vars not set")
    return dsn, user, pw


def test_real_connect_and_query():
    dsn, user, pw = _real_dsn()
    p = ApexBuilderPool()
    profile = Profile(sqlcl_name="X", environment="DEV", workspace="W")
    p.connect(profile=profile, dsn=dsn, user=user, password=pw)
    try:
        with p.acquire() as conn:
            cur = conn.cursor()
            cur.execute("select sys_context('USERENV','CURRENT_SCHEMA') from dual")
            (schema,) = cur.fetchone()
            assert isinstance(schema, str) and len(schema) > 0
    finally:
        p.disconnect()
