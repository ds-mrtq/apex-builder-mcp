# tests/unit/test_state.py
from __future__ import annotations

from apex_builder_mcp.connection.state import ConnectionState
from apex_builder_mcp.schema.profile import Profile


def test_state_starts_unconfigured():
    s = ConnectionState()
    assert s.status == "UNCONFIGURED"
    assert s.profile is None


def test_state_set_profile_moves_to_configured():
    s = ConnectionState()
    s.set_profile(Profile(sqlcl_name="X", environment="DEV", workspace="W"))
    assert s.status == "CONFIGURED"


def test_state_mark_connected():
    s = ConnectionState()
    s.set_profile(Profile(sqlcl_name="X", environment="DEV", workspace="W"))
    s.mark_connected()
    assert s.status == "CONNECTED:DEV"


def test_state_mark_disconnected():
    s = ConnectionState()
    s.set_profile(Profile(sqlcl_name="X", environment="DEV", workspace="W"))
    s.mark_connected()
    s.mark_disconnected()
    assert s.status == "DISCONNECTED"
