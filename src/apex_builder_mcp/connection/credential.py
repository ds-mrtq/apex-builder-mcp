# src/apex_builder_mcp/connection/credential.py
from __future__ import annotations

import getpass

import keyring

SERVICE_NAME = "apex-builder-mcp"


class CredentialError(RuntimeError):
    """Wraps keyring backend failures."""


def set_password(profile_name: str, password: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, profile_name, password)
    except Exception as e:
        raise CredentialError(f"Failed to store password: {e}") from e


def get_password(
    profile_name: str,
    prompt_if_missing: bool = False,
    save_after_prompt: bool = False,
) -> str | None:
    try:
        pw = keyring.get_password(SERVICE_NAME, profile_name)
    except Exception as e:
        raise CredentialError(f"Failed to read password: {e}") from e
    if pw is None and prompt_if_missing:
        pw = getpass.getpass(f"Password for profile '{profile_name}': ")
        if save_after_prompt and pw:
            set_password(profile_name, pw)
    return pw


def delete_password(profile_name: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, profile_name)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception as e:
        raise CredentialError(f"Failed to delete password: {e}") from e
