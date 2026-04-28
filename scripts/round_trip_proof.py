"""Phase 0 Gate 5 — Round-Trip Proof harness (SQLcl-based, no password needed).

Uses `sql -name <conn>` subprocess for all DB ops. SQLcl resolves password
from its own encrypted store — same UX as SQLcl MCP.

Required env vars:
    APEX_TEST_SQLCL_NAME       SQLcl named connection (e.g., ereport_test8001)
    APEX_TEST_WORKSPACE        APEX workspace name (e.g., EREPORT)
    APEX_TEST_SCHEMA           Schema that owns sandbox apps (e.g., EREPORT)
    APEX_TEST_RUNTIME_URL      e.g., https://apexdev.vicemhatien.com.vn/ords/r/ereport
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def _sqlcl(conn_name: str, sql_text: str, *, timeout: int = 120) -> tuple[int, str, str]:
    """Run SQL/PLSQL via `sql -name <conn>`. Return (rc, stdout, stderr)."""
    env = {**os.environ, "MSYS2_ARG_CONV_EXCL": "*"}
    proc = subprocess.run(
        ["sql", "-name", conn_name],
        input=sql_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _strip_sqlcl_banner(out: str) -> str:
    """Drop SQLcl banner / connect lines so we focus on actual results."""
    lines = out.splitlines()
    drop_patterns = [
        r"^SQLcl: Release",
        r"^Copyright \(c\)",
        r"^Connected\.$",
        r"^$",
    ]
    return "\n".join(
        ln for ln in lines if not any(re.match(p, ln) for p in drop_patterns)
    )


def lookup_workspace_id(conn_name: str, workspace: str) -> int:
    sql = f"""set heading off feedback off pagesize 0 echo off
select workspace_id from apex_workspaces where upper(workspace) = '{workspace.upper()}';
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql)
    if rc != 0:
        raise RuntimeError(f"workspace lookup failed rc={rc}: {stderr}")
    # Extract numeric workspace_id
    for line in _strip_sqlcl_banner(stdout).splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    raise RuntimeError(f"Could not parse workspace_id from output:\n{stdout}")


def make_sandbox_app(conn_name: str, app_id: int, ws_id: int, schema: str) -> None:
    sql = f"""set echo off feedback off
begin
  wwv_flow_application_install.set_workspace_id({ws_id});
  wwv_flow_application_install.set_schema('{schema}');
  wwv_flow_application_install.set_application_id({app_id});
  wwv_flow_application_install.generate_offset;
  wwv_flow_imp.create_application(
    p_id => {app_id}, p_owner => '{schema}',
    p_name => '_TEST_APEXBLD_RT_' || {app_id},
    p_alias => '_RT_' || {app_id},
    p_application_group => 0
  );
  wwv_flow_imp_page.create_page(
    p_id => 1, p_name => 'RT_Sandbox', p_step_title => 'RT_Sandbox'
  );
  wwv_flow_imp_page.create_page_plug(
    p_id => 100, p_plug_name => 'RT_Region',
    p_plug_template => 0, p_plug_display_sequence => 10,
    p_plug_source_type => 'NATIVE_HTML',
    p_plug_query_options => 'DERIVED_REPORT_COLUMNS'
  );
  wwv_flow_imp_page.create_page_item(
    p_id => 200, p_name => 'P1_RT_ITEM',
    p_item_sequence => 10, p_item_plug_id => 100,
    p_display_as => 'NATIVE_TEXT_FIELD'
  );
  commit;
end;
/
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=180)
    out = _strip_sqlcl_banner(stdout)
    if rc != 0 or "ORA-" in out or "PLS-" in out:
        raise RuntimeError(
            f"create sandbox failed rc={rc}\nstdout:\n{out}\nstderr:\n{stderr}"
        )


def export_app(conn_name: str, app_id: int, output_dir: Path) -> Path:
    """Use SQLcl's `apex export` command. Returns path of generated .sql."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # apex export -applicationid <id> -dir <dir> writes f<id>.sql
    sql = f"""apex export -applicationid {app_id} -dir {output_dir.as_posix()}
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=180)
    out = _strip_sqlcl_banner(stdout)
    if rc != 0:
        raise RuntimeError(f"export failed rc={rc}\n{out}\nerr:\n{stderr}")
    expected = output_dir / f"f{app_id}.sql"
    if not expected.exists():
        # SQLcl 26 may use different naming — find any .sql in output_dir
        candidates = list(output_dir.glob("*.sql"))
        if not candidates:
            raise RuntimeError(f"export produced no .sql file in {output_dir}\n{out}")
        return candidates[0]
    return expected


def drop_app(conn_name: str, app_id: int) -> None:
    sql = f"""set echo off feedback off
begin
  begin
    wwv_flow_imp.remove_flow({app_id});
  exception when others then null;
  end;
  commit;
end;
/
exit
"""
    _sqlcl(conn_name, sql, timeout=60)


def reimport_app(
    conn_name: str,
    export_file: Path,
    new_app_id: int,
    ws_id: int,
    schema: str,
) -> None:
    # Set offset + workspace + new app id, then run the export script
    sql = f"""set echo off feedback off
begin
  wwv_flow_application_install.set_workspace_id({ws_id});
  wwv_flow_application_install.set_schema('{schema}');
  wwv_flow_application_install.set_application_id({new_app_id});
  wwv_flow_application_install.generate_offset;
end;
/
@{export_file.as_posix()}
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=300)
    out = _strip_sqlcl_banner(stdout)
    if rc != 0 or "ORA-" in out or "PLS-" in out:
        raise RuntimeError(
            f"reimport failed rc={rc}\nstdout:\n{out}\nstderr:\n{stderr}"
        )


def metadata_for_app(conn_name: str, app_id: int) -> dict:
    sql = f"""set heading off feedback off pagesize 0 echo off
select pages from apex_applications where application_id = {app_id};
select count(*) from apex_application_page_regions where application_id = {app_id};
select count(*) from apex_application_page_items where application_id = {app_id};
exit
"""
    rc, stdout, _ = _sqlcl(conn_name, sql)
    if rc != 0:
        raise RuntimeError(f"metadata query failed rc={rc}\n{stdout}")
    nums = [
        int(line.strip())
        for line in _strip_sqlcl_banner(stdout).splitlines()
        if line.strip().isdigit()
    ]
    if len(nums) < 3:
        raise RuntimeError(f"could not parse 3 metadata numbers from:\n{stdout}")
    return {"pages": nums[0], "regions": nums[1], "items": nums[2]}


def verify_runtime_page_open(
    runtime_url: str, app_alias: str, page_id: int = 1
) -> tuple[bool, str]:
    url = f"{runtime_url.rstrip('/')}/{app_alias}/{page_id}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            html = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200:
                return (False, f"HTTP {resp.status}")
            error_markers = [
                "application not found",
                "ORA-",
                "ERR-",
                "WWV_FLOW_IMP",
                "<title>Error",
            ]
            for marker in error_markers:
                if marker in html:
                    return (False, f"error marker '{marker}' in response")
            return (True, "HTTP 200, no error markers")
    except urllib.error.HTTPError as e:
        return (False, f"HTTPError {e.code}: {e.reason}")
    except Exception as e:
        return (False, f"Exception: {type(e).__name__}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("docs/PHASE_0_REPORT.md"))
    args = parser.parse_args()

    required = [
        "APEX_TEST_SQLCL_NAME",
        "APEX_TEST_WORKSPACE",
        "APEX_TEST_SCHEMA",
        "APEX_TEST_RUNTIME_URL",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERROR: missing env vars: {missing}", file=sys.stderr)
        return 2

    conn = os.environ["APEX_TEST_SQLCL_NAME"]
    workspace = os.environ["APEX_TEST_WORKSPACE"]
    schema = os.environ["APEX_TEST_SCHEMA"]
    runtime_url = os.environ["APEX_TEST_RUNTIME_URL"]

    rid = 800000 + secrets.randbelow(99999)
    rid2 = rid + 100

    findings: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "sqlcl_conn": conn,
        "workspace": workspace,
        "schema": schema,
        "steps": [],
    }
    overall_pass = True

    try:
        ws_id = lookup_workspace_id(conn, workspace)
        findings["workspace_id"] = ws_id
        print(f"[Lookup] workspace {workspace} → ID {ws_id}")

        print(f"[1/6] Create sandbox app {rid}")
        make_sandbox_app(conn, rid, ws_id, schema)
        meta_a = metadata_for_app(conn, rid)
        findings["steps"].append(
            {"step": "create_sandbox", "app_id": rid, "metadata": meta_a, "status": "ok"}
        )

        print(f"[2/6] Export app {rid} via `apex export`")
        export_dir = Path(os.environ.get("TEMP", "/tmp")) / f"apex_rt_{rid}"
        export_file = export_app(conn, rid, export_dir)
        findings["steps"].append(
            {
                "step": "export",
                "size_bytes": export_file.stat().st_size,
                "path": str(export_file),
                "status": "ok",
            }
        )

        print(f"[3/6] Drop sandbox {rid}")
        drop_app(conn, rid)
        findings["steps"].append({"step": "drop_sandbox", "app_id": rid, "status": "ok"})

        print(f"[4/6] Re-import as app {rid2}")
        reimport_app(conn, export_file, rid2, ws_id, schema)
        meta_b = metadata_for_app(conn, rid2)
        findings["steps"].append(
            {"step": "reimport", "app_id": rid2, "metadata": meta_b, "status": "ok"}
        )

        print("[5/6] Compare metadata")
        if meta_a != meta_b:
            findings["steps"].append(
                {
                    "step": "metadata_match",
                    "status": "fail",
                    "before": meta_a,
                    "after": meta_b,
                }
            )
            overall_pass = False
            print(f"  FAIL — mismatch: {meta_a} vs {meta_b}")
        else:
            findings["steps"].append({"step": "metadata_match", "status": "ok"})
            print("  PASS — metadata identity")

        print(f"[6/6] Verify runtime page open (alias=_RT_{rid2}, page=1)")
        ok, info = verify_runtime_page_open(runtime_url, f"_RT_{rid2}", 1)
        findings["steps"].append(
            {"step": "runtime_open", "status": "ok" if ok else "fail", "detail": info}
        )
        if not ok:
            overall_pass = False
            print(f"  FAIL — {info}")
        else:
            print(f"  PASS — {info}")
    except Exception as e:
        findings["steps"].append({"step": "exception", "status": "fail", "detail": str(e)})
        overall_pass = False
        print(f"\nERROR: {e}", file=sys.stderr)
    finally:
        try:
            drop_app(conn, rid)
        except Exception:
            pass
        try:
            drop_app(conn, rid2)
        except Exception:
            pass

    findings["overall"] = "PASS" if overall_pass else "FAIL"

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("a", encoding="utf-8") as fh:
        fh.write("\n\n## Gate 5 Round-Trip Proof Findings (SQLcl-based)\n\n")
        fh.write("```json\n")
        fh.write(json.dumps(findings, indent=2, ensure_ascii=False))
        fh.write("\n```\n")

    print(f"\n=== ROUND-TRIP RESULT: {findings['overall']} ===")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
