# src/apex_builder_mcp/schema/errors.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ApexBuilderError(Exception):
    code: str
    message: str
    suggestion: str
    sql_attempted: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
