"""Phase 0 Gate 5 — Round-Trip Proof harness.

Steps:
1. Create sandbox app via wwv_flow_imp + wwv_flow_imp_page calls
2. Add 1 page + 1 region + 1 item via internal API
3. Export the app via APEX public API (apex_export.get_application)
4. Drop sandbox + re-import the export into a fresh sandbox app id
5. Compare metadata: page count, region count, item count
6. Open the page in App Builder runtime URL and verify HTTP 200
7. Cleanup both sandboxes
8. Print PASS/FAIL summary + write JSON report

Run: python scripts/round_trip_proof.py

Required env vars:
    APEX_TEST_DSN              e.g., ebstest.vicemhatien.vn:1522/TEST1
    APEX_TEST_USER             schema user (must have grants on wwv_flow_imp_page,
                               wwv_flow_imp, wwv_flow_application_install, apex_export)
    APEX_TEST_PASSWORD         (set locally only; never commit/log)
    APEX_TEST_WORKSPACE_ID     numeric APEX workspace id (query from
                               apex_workspaces if unsure)
    APEX_TEST_SCHEMA           schema that owns the sandbox app (e.g., EREPORT)
    APEX_TEST_RUNTIME_URL      e.g., http://ebstest.vicemhatien.vn:8001/ords/r/<workspace>
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import oracledb


def make_sandbox_app(conn, app_id: int, ws_id: int, schema: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        begin
          wwv_flow_application_install.set_workspace_id(:ws);
          wwv_flow_application_install.set_schema(:sc);
          wwv_flow_application_install.set_application_id(:aid);
          wwv_flow_application_install.generate_offset;
          wwv_flow_imp.create_application(
            p_id => :aid, p_owner => :sc,
            p_name => '_TEST_APEXBLD_RT_' || :aid,
            p_alias => '_RT_' || :aid,
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
        """,
        ws=ws_id, sc=schema, aid=app_id,
    )


def export_app_via_public_api(conn, app_id: int, output_path: Path) -> None:
    cur = conn.cursor()
    clob_var = cur.var(oracledb.DB_TYPE_CLOB)
    cur.execute(
        """
        declare
          l_files apex_t_export_files;
        begin
          l_files := apex_export.get_application(p_application_id => :app_id);
          :out := l_files(1).contents;
        end;
        """,
        app_id=app_id,
        out=clob_var,
    )
    output_path.write_text(clob_var.getvalue(), encoding="utf-8")


def drop_app(conn, app_id: int) -> None:
    cur = conn.cursor()
    try:
        cur.execute("begin wwv_flow_imp.remove_flow(:a); commit; end;", a=app_id)
    except Exception as e:
        print(f"WARN: drop_app({app_id}) failed: {e}")


def reimport_app(conn, export_file: Path, new_app_id: int, ws_id: int, schema: str) -> None:
    sql_text = export_file.read_text(encoding="utf-8")
    cur = conn.cursor()
    cur.execute(
        """
        begin
          wwv_flow_application_install.set_workspace_id(:ws);
          wwv_flow_application_install.set_schema(:sc);
          wwv_flow_application_install.set_application_id(:aid);
          wwv_flow_application_install.generate_offset;
        end;
        """,
        ws=ws_id, sc=schema, aid=new_app_id,
    )
    cur.execute(sql_text)
    conn.commit()


def metadata_for_app(conn, app_id: int) -> dict:
    cur = conn.cursor()
    cur.execute(
        "select pages from apex_applications where application_id = :a",
        a=app_id,
    )
    page_count = cur.fetchone()[0]
    cur.execute(
        "select count(*) from apex_application_page_regions where application_id = :a",
        a=app_id,
    )
    region_count = cur.fetchone()[0]
    cur.execute(
        "select count(*) from apex_application_page_items where application_id = :a",
        a=app_id,
    )
    item_count = cur.fetchone()[0]
    return {"pages": page_count, "regions": region_count, "items": item_count}


def verify_runtime_page_open(
    runtime_url: str, app_alias: str, page_id: int = 1
) -> tuple[bool, str]:
    """GET the page; verify HTTP 200 and no error markers. Returns (ok, info_string)."""
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
                    return (False, f"Found error marker '{marker}' in response")
            return (True, "HTTP 200, no error markers")
    except urllib.error.HTTPError as e:
        return (False, f"HTTPError {e.code}: {e.reason}")
    except Exception as e:
        return (False, f"Exception: {type(e).__name__}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("docs/PHASE_0_REPORT.md"))
    args = parser.parse_args()

    required_vars = [
        "APEX_TEST_DSN", "APEX_TEST_USER", "APEX_TEST_PASSWORD",
        "APEX_TEST_WORKSPACE_ID", "APEX_TEST_SCHEMA", "APEX_TEST_RUNTIME_URL",
    ]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"ERROR: missing env vars: {missing}", file=sys.stderr)
        return 2

    dsn = os.environ["APEX_TEST_DSN"]
    user = os.environ["APEX_TEST_USER"]
    pw = os.environ["APEX_TEST_PASSWORD"]
    ws_id = int(os.environ["APEX_TEST_WORKSPACE_ID"])
    schema = os.environ["APEX_TEST_SCHEMA"]
    runtime_url = os.environ["APEX_TEST_RUNTIME_URL"]

    rid = 800000 + secrets.randbelow(99999)
    rid2 = rid + 100
    conn = oracledb.connect(user=user, password=pw, dsn=dsn)
    findings: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "test_dsn": dsn.split("@")[-1] if "@" in dsn else dsn,  # don't log creds
        "test_user": user,
        "workspace_id": ws_id,
        "steps": [],
    }
    overall_pass = True

    try:
        print(f"[1/6] Create sandbox app {rid}")
        make_sandbox_app(conn, rid, ws_id, schema)
        meta_a = metadata_for_app(conn, rid)
        findings["steps"].append({
            "step": "create_sandbox",
            "app_id": rid,
            "metadata": meta_a,
            "status": "ok",
        })

        print(f"[2/6] Export app {rid}")
        # Use cross-platform tmp dir
        export_path = Path(os.environ.get("TEMP", "/tmp")) / f"apex_rt_{rid}.sql"
        export_app_via_public_api(conn, rid, export_path)
        findings["steps"].append({
            "step": "export",
            "size_bytes": export_path.stat().st_size,
            "path": str(export_path),
            "status": "ok",
        })

        print(f"[3/6] Drop sandbox {rid}")
        drop_app(conn, rid)
        findings["steps"].append({"step": "drop_sandbox", "app_id": rid, "status": "ok"})

        print(f"[4/6] Re-import as app {rid2}")
        reimport_app(conn, export_path, rid2, ws_id, schema)
        meta_b = metadata_for_app(conn, rid2)
        findings["steps"].append({
            "step": "reimport", "app_id": rid2, "metadata": meta_b, "status": "ok"
        })

        print("[5/6] Compare metadata")
        if meta_a != meta_b:
            findings["steps"].append({
                "step": "metadata_match", "status": "fail",
                "before": meta_a, "after": meta_b,
            })
            overall_pass = False
            print(f"  FAIL — metadata mismatch: {meta_a} vs {meta_b}")
        else:
            findings["steps"].append({"step": "metadata_match", "status": "ok"})
            print("  PASS — metadata identity")

        print(f"[6/6] Verify runtime page open (app_alias=_RT_{rid2}, page=1)")
        runtime_ok, runtime_info = verify_runtime_page_open(runtime_url, f"_RT_{rid2}", 1)
        if not runtime_ok:
            findings["steps"].append({
                "step": "runtime_open", "status": "fail", "detail": runtime_info,
            })
            overall_pass = False
            print(f"  FAIL — {runtime_info}")
        else:
            findings["steps"].append({
                "step": "runtime_open", "status": "ok", "detail": runtime_info,
            })
            print(f"  PASS — {runtime_info}")
    finally:
        drop_app(conn, rid)
        drop_app(conn, rid2)
        conn.close()

    findings["overall"] = "PASS" if overall_pass else "FAIL"

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("a", encoding="utf-8") as fh:
        fh.write("\n\n## Gate 5 Round-Trip Proof Findings\n\n")
        fh.write("```json\n")
        fh.write(json.dumps(findings, indent=2, ensure_ascii=False))
        fh.write("\n```\n")

    print(f"\n=== ROUND-TRIP RESULT: {findings['overall']} ===")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
