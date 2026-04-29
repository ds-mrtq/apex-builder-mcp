"""Auto-export hook — refresh split-export file after write tool succeeds.

Runs SQLcl `apex export -applicationid <id> -dir <export_dir>` to refresh
the local split-export, giving the user a git-trackable view of the change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from apex_builder_mcp.connection.sqlcl_subprocess import has_db_error, run_sqlcl


def refresh_export(
    sqlcl_conn: str,
    app_id: int,
    export_dir: Path | None,
) -> dict[str, Any]:
    """Refresh APEX export for the given app via SQLcl `apex export`.

    Returns a result dict:
        {"skipped": True, "reason": "..."}                      # when export_dir is None
        {"skipped": False, "ok": True, "app_id": ..., "export_path": "..."}
        {"skipped": False, "ok": False, "error": "..."}
    """
    if export_dir is None:
        return {"skipped": True, "reason": "auto_export_dir not set in profile"}
    export_dir.mkdir(parents=True, exist_ok=True)
    sql = f"apex export -applicationid {app_id} -dir {export_dir.as_posix()}\nexit\n"
    result = run_sqlcl(sqlcl_conn, sql, timeout=300)
    if result.rc != 0 or has_db_error(result.stdout):
        return {
            "skipped": False,
            "ok": False,
            "app_id": app_id,
            "error": result.cleaned,
        }
    expected = export_dir / f"f{app_id}.sql"
    return {
        "skipped": False,
        "ok": True,
        "app_id": app_id,
        "export_path": str(expected) if expected.exists() else str(export_dir),
    }
