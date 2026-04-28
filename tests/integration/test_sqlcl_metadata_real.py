"""Gate 4: read SQLcl named connection metadata from real SQL Developer Extension store."""
from __future__ import annotations

import os

import pytest

from apex_builder_mcp.connection.sqlcl_metadata import (
    SqlclConnectionNotFoundError,
    read_connection_metadata,
)

pytestmark = pytest.mark.integration


def test_read_real_sqlcl_connection():
    name = os.environ.get("APEX_TEST_SQLCL_NAME")
    if not name:
        pytest.skip("APEX_TEST_SQLCL_NAME not set")
    try:
        md = read_connection_metadata(name)
    except FileNotFoundError as e:
        pytest.fail(
            f"Gate 4 FAIL: SQLcl connections file not found at the expected path. "
            f"User's SQLcl 26+ may use a different storage format. "
            f"This is a known limitation — see PHASE_0_GATE_4.md fallback. "
            f"Underlying error: {e}"
        )
    except SqlclConnectionNotFoundError:
        pytest.fail(
            f"Gate 4 FAIL: connection '{name}' not found in connections file. "
            f"Verify name with `sql /nolog` then `connmgr list`."
        )
    assert md.host
    assert md.port > 0
    assert md.service_name
    assert md.user
    # MUST NOT have password
    assert not hasattr(md, "password")
    print(f"\nResolved {name}: {md.user}@{md.dsn}")
