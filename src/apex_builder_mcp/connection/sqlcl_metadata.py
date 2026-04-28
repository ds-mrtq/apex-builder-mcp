# src/apex_builder_mcp/connection/sqlcl_metadata.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class SqlclConnectionNotFound(KeyError):  # noqa: N818
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


def read_connection_metadata(
    name: str,
    connections_file: Path | None = None,
) -> SqlclConnectionMetadata:
    f = connections_file or _default_connections_file()
    if not f.exists():
        raise FileNotFoundError(f"SQLcl connections file not found: {f}")
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
    raise SqlclConnectionNotFound(name)
