"""Gate 3: keyring (Windows Credential Manager) round-trip on user's machine."""
from __future__ import annotations

import secrets

import pytest

from apex_builder_mcp.connection.credential import (
    delete_password,
    get_password,
    set_password,
)

pytestmark = pytest.mark.integration


def test_keyring_round_trip():
    test_profile = f"_apexbld_gate3_{secrets.token_hex(4)}"
    test_password = f"test-{secrets.token_urlsafe(16)}"
    try:
        set_password(test_profile, test_password)
        retrieved = get_password(test_profile)
        assert retrieved == test_password
    finally:
        delete_password(test_profile)
        # Verify cleanup worked
        assert get_password(test_profile) is None
