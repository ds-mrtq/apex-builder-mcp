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

# ORA codes that indicate the DB itself is unreachable (instance down, listener
# not running, network blocked, credentials revoked) — distinct from regular
# query failures. When SQLcl rc!=0 and one of these appears in stdout/stderr,
# we raise DB_UNREACHABLE with an actionable suggestion instead of the generic
# SQLCL_QUERY_FAIL.
_CONNECTION_ORA_HINTS: dict[str, str] = {
    "ORA-12514": "Listener is up but the service name isn't registered yet "
                 "(DB instance probably starting, stopped, or in restricted mode)",
    "ORA-12541": "No listener at the target host:port (listener process not running)",
    "ORA-12170": "TNS connect timeout — network reachable but no response",
    "ORA-12545": "Connect failed — target host unreachable (network or DNS issue)",
    "ORA-12154": "TNS could not resolve the connect identifier (saved-connection "
                 "definition broken — run `connmgr show <name>` to inspect)",
    "ORA-12162": "TNS net service name incorrectly specified",
    "ORA-01017": "Invalid username/password (credentials in SQLcl saved-conn "
                 "may have been rotated)",
    "ORA-28000": "DB user account is locked — DBA must unlock",
    "ORA-28001": "DB password has expired — rotate via `alter user ... identified by ...`",
    "ORA-12526": "Listener in restricted mode — DB DBA-only",
    "ORA-12528": "Listener blocking new connections",
}


class SqlclSubprocessError(RuntimeError):
    """Raised when SQLcl subprocess returns a non-zero exit or DB error."""


def classify_sqlcl_failure(result: "SqlclResult") -> dict[str, str] | None:
    """Inspect a failed SqlclResult; return a dict if it looks like a
    DB-unreachable failure (ORA-12514 etc.), or a generic-rc failure with
    a recognisable phrase ("Connection refused" / "Connection failed").
    Returns None for unrecognised failures (caller falls back to generic).

    Shape: {"ora_code": "ORA-12514", "ora_line": "<full line>", "hint": "..."}
    """
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    for ora, hint in _CONNECTION_ORA_HINTS.items():
        if ora in combined:
            for line in combined.splitlines():
                if ora in line:
                    return {
                        "ora_code": ora,
                        "ora_line": line.strip(),
                        "hint": hint,
                    }
    lower = combined.lower()
    if "connection refused" in lower or "connection failed" in lower:
        # Surface the most informative line
        for line in combined.splitlines():
            ll = line.lower()
            if "connection refused" in ll or "connection failed" in ll:
                return {
                    "ora_code": "",
                    "ora_line": line.strip(),
                    "hint": "Network unreachable or DB process not running",
                }
    return None


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
    """Run SQL/PLSQL via `sql -name <conn>`. Returns rc/stdout/stderr.

    Bug #3 (HT_AMMS 2026-05-20): SQLcl on Windows defaults to
    NLS_LANG=AMERICAN_AMERICA.WE8MSWIN1252 unless overridden, which
    double-encodes UTF-8 strings passed in via stdin (e.g. "Cấu hình" stored
    as "Cáº¥u hÃ¬nh"). We pipe `sql_text` as UTF-8 bytes, so we must tell
    SQLcl the client charset is also UTF-8 to round-trip cleanly into the
    UTF8/AL32UTF8 DB. APEX_BUILDER_NLS_LANG env var overrides; otherwise
    we default to AL32UTF8.
    """
    nls_lang = os.environ.get(
        "APEX_BUILDER_NLS_LANG", "AMERICAN_AMERICA.AL32UTF8"
    )
    env = {
        **os.environ,
        "MSYS2_ARG_CONV_EXCL": "*",
        "NLS_LANG": nls_lang,
    }
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
