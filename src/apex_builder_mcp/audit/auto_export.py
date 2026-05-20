"""Auto-export hook — refresh split-export file after write tool succeeds.

Runs SQLcl `apex export -applicationid <id> -dir <export_dir>` to refresh
the local split-export, giving the user a git-trackable view of the change.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from apex_builder_mcp.connection.sqlcl_subprocess import has_db_error, run_sqlcl


def _newest_mtime(p: Path) -> float:
    """Most recent mtime across all files under p (recursive). 0 if empty."""
    latest = 0.0
    for f in p.rglob("*"):
        if f.is_file():
            t = f.stat().st_mtime
            if t > latest:
                latest = t
    return latest


def refresh_export(
    sqlcl_conn: str,
    app_id: int,
    export_dir: Path | None,
) -> dict[str, Any]:
    """Refresh APEX export for the given app via SQLcl `apex export`.

    Returns a result dict with shape:
        {"skipped": True, "reason": "..."}                      # when export_dir is None
        {"skipped": False, "ok": True,  "app_id": ..., "export_path": ..., "file_count": N, "newest_file": "..."}
        {"skipped": False, "ok": False, "app_id": ..., "error": "...", "sqlcl_rc": N, "stdout_tail": "..."}

    Verifies that SQLcl actually wrote at least one file with mtime newer
    than when we entered the function. Without this verify, SQLcl can return
    rc=0 + no DB error while silently writing nothing (Bug #5 from
    HT_AMMS 2026-05-20 — `apex export` failed but reported ok).
    """
    if export_dir is None:
        return {"skipped": True, "reason": "auto_export_dir not set in profile"}
    export_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot directory state BEFORE the export so we can verify writes
    # actually landed (mtime-based — works whether SQLcl writes f<id>.sql,
    # a split tree, or a different layout per app config).
    before_mtime = _newest_mtime(export_dir)
    # Subtract 1s epsilon: Windows file mtime granularity can be coarser
    # than time.time(), so a file written right after `started` could have
    # mtime slightly less than `started` and falsely fail the verify.
    started = time.time() - 1.0

    sql = f"apex export -applicationid {app_id} -dir {export_dir.as_posix()}\nexit\n"
    result = run_sqlcl(sqlcl_conn, sql, timeout=300)

    if result.rc != 0 or has_db_error(result.stdout):
        return {
            "skipped": False,
            "ok": False,
            "app_id": app_id,
            "error": result.cleaned,
            "sqlcl_rc": result.rc,
            "stdout_tail": result.stdout[-500:],
            "stderr_tail": result.stderr[-500:],
        }

    # Verify a file actually landed. Two signals (either is sufficient):
    #   (a) f<id>.sql exists — the canonical single-file export
    #   (b) at least one file in the tree has mtime > started_at — split-mode
    after_mtime = _newest_mtime(export_dir)
    canonical = export_dir / f"f{app_id}.sql"
    canonical_exists = canonical.exists()
    fresh_write = after_mtime >= started

    if not (canonical_exists or fresh_write):
        # SQLcl reported rc=0 but nothing was actually written. This is the
        # Bug #5 silent-fail mode. Surface evidence so the user can debug.
        files = sorted(p.relative_to(export_dir).as_posix() for p in export_dir.rglob("*") if p.is_file())[:10]
        return {
            "skipped": False,
            "ok": False,
            "app_id": app_id,
            "error": "FILE_NOT_PERSISTED",
            "detail": (
                f"sqlcl returned rc=0 with no DB error but no new file landed "
                f"in {export_dir.as_posix()!r}. Existing files: {files}. "
                f"Likely SQLcl `apex export` command failed silently — try "
                f"running it manually: `sql -name {sqlcl_conn}` then "
                f"`apex export -applicationid {app_id} -dir <dir>`."
            ),
            "sqlcl_rc": result.rc,
            "stdout_tail": result.stdout[-500:],
            "before_mtime": before_mtime,
            "after_mtime": after_mtime,
            "started_at": started,
        }

    # Count + identify newest file for diagnostic visibility
    files_after = [p for p in export_dir.rglob("*") if p.is_file()]
    newest = max(files_after, key=lambda p: p.stat().st_mtime, default=None)

    return {
        "skipped": False,
        "ok": True,
        "app_id": app_id,
        "export_path": str(canonical) if canonical_exists else str(export_dir),
        "file_count": len(files_after),
        "newest_file": str(newest.relative_to(export_dir)) if newest else None,
    }
