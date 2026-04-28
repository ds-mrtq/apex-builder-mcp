# tests/unit/test_credential.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.credential import (
    CredentialError,
    delete_password,
    get_password,
    set_password,
)


def test_set_then_get_password(monkeypatch):
    storage: dict[str, str] = {}
    fake_keyring = MagicMock()
    fake_keyring.set_password = lambda svc, user, pw: storage.update({f"{svc}:{user}": pw})
    fake_keyring.get_password = lambda svc, user: storage.get(f"{svc}:{user}")
    fake_keyring.delete_password = lambda svc, user: storage.pop(f"{svc}:{user}", None)

    monkeypatch.setattr("apex_builder_mcp.connection.credential.keyring", fake_keyring)

    set_password("DEV1", "secret123")
    assert get_password("DEV1") == "secret123"

    delete_password("DEV1")
    assert get_password("DEV1") is None


def test_get_password_with_prompt_fallback(monkeypatch):
    fake_keyring = MagicMock()
    fake_keyring.get_password = lambda svc, user: None
    fake_keyring.set_password = MagicMock()

    monkeypatch.setattr("apex_builder_mcp.connection.credential.keyring", fake_keyring)
    monkeypatch.setattr(
        "apex_builder_mcp.connection.credential.getpass.getpass",
        lambda prompt: "from-prompt",
    )

    pw = get_password("NEW_PROFILE", prompt_if_missing=True, save_after_prompt=True)
    assert pw == "from-prompt"
    fake_keyring.set_password.assert_called_once()


def test_keyring_error_wrapped(monkeypatch):
    fake_keyring = MagicMock()
    fake_keyring.get_password = MagicMock(side_effect=Exception("backend failure"))
    monkeypatch.setattr("apex_builder_mcp.connection.credential.keyring", fake_keyring)

    with pytest.raises(CredentialError):
        get_password("X")
