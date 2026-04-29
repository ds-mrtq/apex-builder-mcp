# src/apex_builder_mcp/connection/sqlcl_subprocess.py
"""Run SQL/PLSQL via SQLcl saved connection (no password handling).

The same UX as Oracle's SQLcl MCP — caller specifies a saved connection
name and SQLcl resolves credentials from its own encrypted store. This
module never sees the password.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

_BANNER_PATTERNS = [
    r"^SQLcl: Release",
    r"^Copyright \(c\)",
    r"^Connected to:$",
    r"^Connected\.$",
    r"^Oracle Database",
    r"^Version 19",
    r"^Disconnected from",
    r"^$",
]

_DB_ERROR_RE = re.compile(r"(ORA-\d+|PLS-\d+)")


class SqlclSubprocessError(RuntimeError):
    """Raised when SQLcl subprocess returns a non-zero exit or DB error."""


@dataclass(frozen=True)
class SqlclResult:
    rc: int
    stdout: str
    stderr: str

    @property
    def cleaned(self) -> str:
        return strip_banner(self.stdout)


def strip_banner(out: str) -> str:
    """Drop SQLcl banner / connect lines so we focus on actual results."""
    return "\n".join(
        ln
        for ln in out.splitlines()
        if not any(re.match(p, ln) for p in _BANNER_PATTERNS)
    )


def has_db_error(out: str) -> bool:
    return bool(_DB_ERROR_RE.search(out))


def run_sqlcl(
    conn_name: str,
    sql_text: str,
    *,
    timeout: int = 180,
    raise_on_db_error: bool = False,
) -> SqlclResult:
    """Run SQL/PLSQL via `sql -name <conn>`. Returns rc/stdout/stderr."""
    env = {**os.environ, "MSYS2_ARG_CONV_EXCL": "*"}
    proc = subprocess.run(
        ["sql", "-name", conn_name],
        input=sql_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    result = SqlclResult(rc=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if raise_on_db_error and (result.rc != 0 or has_db_error(result.stdout)):
        raise SqlclSubprocessError(
            f"SQLcl call failed (rc={result.rc}):\n{result.cleaned}\nstderr:\n{result.stderr}"
        )
    return result
