# src/apex_builder_mcp/guard/dry_run.py
from __future__ import annotations

from typing import Any


def _emit_value(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    raise TypeError(f"Unsupported type for SQL emit: {type(v)}")


def render_plsql_call(proc_name: str, params: dict[str, Any]) -> str:
    """Render a PL/SQL anonymous block calling proc_name with named params.

    Emits real PL/SQL booleans (not quoted) to avoid PLS-00306.
    """
    arg_lines = ",\n    ".join(f"{name} => {_emit_value(v)}" for name, v in params.items())
    return f"begin\n  {proc_name}(\n    {arg_lines}\n  );\nend;"
