# src/apex_builder_mcp/connection/sqlcl_metadata.py
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# SQLcl 26.1 emits plain text when stdout is a pipe, but future versions or
# different TERM settings could emit CSI sequences. Strip them defensively so
# field parsing stays robust.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(s: str) -> str:
    return _ANSI_CSI_RE.sub("", s)


class SqlclConnectionNotFoundError(KeyError):
    """Connection name not found in SQLcl/SQL Developer connections store."""


@dataclass(frozen=True)
class SqlclConnectionMetadata:
    name: str
    host: str
    port: int
    service_name: str
    user: str

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service_name}"


def _default_connections_file() -> Path:
    """Best-guess location for SQL Developer Extension connections file on Windows."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return (
            Path(appdata)
            / "Code"
            / "User"
            / "globalStorage"
            / "oracle.sql-developer"
            / "connections.json"
        )
    return Path.home() / ".oracle" / "sqlcl" / "connections.json"


def _parse_connmgr_show(output: str, name: str) -> SqlclConnectionMetadata:
    """Parse output of `sql /nolog` -> `connmgr show <name>`.

    Expected format:
        Name: <conn>
        Connect String: <host>:<port>/<service>
        User: <user>
        Password: ******
    """
    fields: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line)
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().lower()] = val.strip()
    connect_str = fields.get("connect string", "")
    if not connect_str or "/" not in connect_str or ":" not in connect_str:
        raise SqlclConnectionNotFoundError(
            f"connmgr output for '{name}' missing valid Connect String"
        )
    host_port, service = connect_str.rsplit("/", 1)
    host, port_str = host_port.rsplit(":", 1)
    user = fields.get("user", "")
    return SqlclConnectionMetadata(
        name=name,
        host=host.strip(),
        port=int(port_str.strip()),
        service_name=service.strip(),
        user=user.strip(),
    )


def _read_via_connmgr(name: str) -> SqlclConnectionMetadata:
    """Fallback: invoke `sql /nolog` + `connmgr show <name>`."""
    sql = f"connmgr show {name}\nexit\n"
    env = {**os.environ, "MSYS2_ARG_CONV_EXCL": "*"}
    try:
        proc = subprocess.run(
            ["sql", "/nolog"],
            input=sql,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        last_out = (e.stdout or "")[-500:] if isinstance(e.stdout, str) else ""
        last_err = (e.stderr or "")[-500:] if isinstance(e.stderr, str) else ""
        raise SqlclConnectionNotFoundError(
            f"sql connmgr show {name} timed out after 30s. "
            f"last stdout: {last_out!r} last stderr: {last_err!r}"
        ) from e
    if proc.returncode != 0:
        raise SqlclConnectionNotFoundError(
            f"sql connmgr show {name} failed (rc={proc.returncode}): "
            f"stdout={proc.stdout[-500:]!r} stderr={proc.stderr[-500:]!r}"
        )
    return _parse_connmgr_show(proc.stdout, name)


def read_connection_metadata(
    name: str,
    connections_file: Path | None = None,
) -> SqlclConnectionMetadata:
    f = connections_file or _default_connections_file()
    # Try JSON file first (VS Code Extension format)
    if f.exists():
        raw = json.loads(f.read_text(encoding="utf-8"))
        for conn in raw.get("connections", []):
            if conn.get("name") == name:
                return SqlclConnectionMetadata(
                    name=conn["name"],
                    host=conn["host"],
                    port=int(conn["port"]),
                    service_name=conn["serviceName"],
                    user=conn["user"],
                )
    # Fall back to SQLcl 26 connmgr subprocess
    return _read_via_connmgr(name)
