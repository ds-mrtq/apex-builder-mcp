# src/apex_builder_mcp/apex_api/all_arguments.py
from __future__ import annotations

from typing import Any


class SignatureMismatchError(ValueError):
    """Raised when a tool call uses a param name not in the cached signature."""


class SignatureCache:
    """Caches procedure signatures from ALL_ARGUMENTS to avoid PLS-00306."""

    def __init__(self) -> None:
        self._cache: dict[str, list[str]] = {}

    def set(self, qualified_name: str, args: list[str]) -> None:
        self._cache[qualified_name.upper()] = [a.upper() for a in args]

    def get(self, qualified_name: str) -> list[str] | None:
        return self._cache.get(qualified_name.upper())

    def lookup(self, qualified_name: str, connection: Any) -> list[str]:
        """Get from cache or query ALL_ARGUMENTS via given oracledb connection."""
        cached = self.get(qualified_name)
        if cached is not None:
            return cached
        owner, package_proc = (
            qualified_name.split(".", 1)
            if "." in qualified_name
            else ("APEX_240200", qualified_name)
        )
        if "." in package_proc:
            package, proc = package_proc.split(".", 1)
        else:
            package = None
            proc = package_proc
        cur = connection.cursor()
        if package:
            cur.execute(
                """
                select argument_name
                  from all_arguments
                 where owner = :owner
                   and package_name = :pkg
                   and object_name = :proc
                   and argument_name is not null
                 order by sequence
                """,
                owner=owner.upper(),
                pkg=package.upper(),
                proc=proc.upper(),
            )
        else:
            cur.execute(
                """
                select argument_name
                  from all_arguments
                 where owner = :owner
                   and object_name = :proc
                   and argument_name is not null
                 order by sequence
                """,
                owner=owner.upper(),
                proc=proc.upper(),
            )
        args = [row[0] for row in cur.fetchall()]
        self.set(qualified_name, args)
        return args


def verify_call_against_signature(
    proc_name: str,
    signature: list[str],
    used_params: list[str],
) -> None:
    sig_set = {s.upper() for s in signature}
    used_set = {u.upper() for u in used_params}
    unknown = used_set - sig_set
    if unknown:
        raise SignatureMismatchError(
            f"Call to {proc_name} uses unknown params: {sorted(unknown)}. "
            f"Known signature: {signature}"
        )
