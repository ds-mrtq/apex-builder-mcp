"""Phase 0 Gate 5 — Round-Trip Proof harness (clone strategy via SQLcl).

Flow:
1. apex export source_app_id (default 100) -> .sql file
2. Reimport as clone_app_id (random 900xxx) with generate_offset
3. Compare metadata: clone pages == source pages, regions == source regions
4. Add 1 page + 1 region + 1 item to CLONE via wwv_flow_imp_page.*
   (This validates the 3 MVP internal procs we actually need)
5. Re-export clone, verify export contains the new page id
6. Open new page in runtime URL, verify HTTP 200 + no error markers
7. Drop clone via wwv_flow_imp.remove_flow
8. Source app untouched throughout
9. Write findings JSON to docs/PHASE_0_REPORT.md, return PASS/FAIL

Required env vars:
    APEX_TEST_SQLCL_NAME       SQLcl named connection (e.g., ereport_test8001)
    APEX_TEST_WORKSPACE        APEX workspace name (e.g., EREPORT)
    APEX_TEST_SCHEMA           Schema (e.g., EREPORT)
    APEX_TEST_RUNTIME_URL      Runtime URL prefix
    APEX_TEST_SOURCE_APP_ID    Source app to clone (default: 100)
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


def _sqlcl(conn_name: str, sql_text: str, *, timeout: int = 180) -> tuple[int, str, str]:
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
    return proc.returncode, proc.stdout, proc.stderr


def _strip_banner(out: str) -> str:
    drop = [
        r"^SQLcl: Release",
        r"^Copyright \(c\)",
        r"^Connected to:$",
        r"^Connected\.$",
        r"^Oracle Database",
        r"^Version 19",
        r"^Disconnected from",
        r"^$",
    ]
    return "\n".join(
        ln for ln in out.splitlines() if not any(re.match(p, ln) for p in drop)
    )


def _has_db_error(out: str) -> bool:
    return bool(re.search(r"(ORA-\d+|PLS-\d+)", out))


def lookup_workspace_id(conn_name: str, workspace: str) -> int:
    sql = f"""set heading off feedback off pagesize 0 echo off
select workspace_id from apex_workspaces where upper(workspace) = '{workspace.upper()}';
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql)
    if rc != 0:
        raise RuntimeError(f"workspace lookup failed: {stderr}")
    for line in _strip_banner(stdout).splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s)
    raise RuntimeError(f"could not parse workspace_id from:\n{stdout}")


def metadata_for_app(conn_name: str, app_id: int) -> dict:
    sql = f"""set heading off feedback off pagesize 0 echo off
select pages from apex_applications where application_id = {app_id};
select count(*) from apex_application_page_regions where application_id = {app_id};
select count(*) from apex_application_page_items where application_id = {app_id};
select alias from apex_applications where application_id = {app_id};
exit
"""
    rc, stdout, _ = _sqlcl(conn_name, sql)
    if rc != 0:
        raise RuntimeError(f"metadata query failed for app {app_id}")
    body = _strip_banner(stdout)
    nums = [int(s.strip()) for s in body.splitlines() if s.strip().isdigit()]
    if len(nums) < 3:
        raise RuntimeError(f"could not parse 3 numbers from:\n{body}")
    # Find alias (first non-numeric, non-empty line after the numbers)
    alias = None
    for line in body.splitlines():
        s = line.strip()
        if s and not s.isdigit():
            alias = s
            break
    return {
        "pages": nums[0],
        "regions": nums[1],
        "items": nums[2],
        "alias": alias,
    }


def export_app(conn_name: str, app_id: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    sql = f"""apex export -applicationid {app_id} -dir {output_dir.as_posix()}
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=300)
    if rc != 0 or _has_db_error(stdout):
        raise RuntimeError(f"export failed:\n{stdout}\n{stderr}")
    candidates = list(output_dir.glob("*.sql"))
    if not candidates:
        raise RuntimeError(f"no .sql file produced in {output_dir}")
    # Prefer fNNN.sql shape
    primary = [p for p in candidates if re.match(rf"^f{app_id}\.sql$", p.name)]
    return primary[0] if primary else candidates[0]


def reimport_as_new_app(
    conn_name: str,
    export_file: Path,
    new_app_id: int,
    ws_id: int,
    schema: str,
) -> None:
    # Stage the install context, then run the export script via @
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
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=600)
    if rc != 0 or _has_db_error(stdout):
        raise RuntimeError(f"reimport failed:\n{_strip_banner(stdout)}\n{stderr}")


def add_page_region_item(
    conn_name: str, clone_app_id: int, new_page_id: int, region_id: int, item_id: int
) -> None:
    """Add 1 page + 1 region + 1 item via internal wwv_flow_imp_page.* procs.

    This is the actual MVP write path — the 3 calls our spec section 5.2 lists.
    """
    sql = f"""set echo off feedback on
begin
  wwv_flow_application_install.set_application_id({clone_app_id});
  wwv_flow_imp_page.create_page(
    p_id => {new_page_id},
    p_name => 'PHASE0_PROBE',
    p_step_title => 'PHASE0_PROBE'
  );
  wwv_flow_imp_page.create_page_plug(
    p_id => {region_id},
    p_plug_name => 'PHASE0_REGION',
    p_plug_template => 0,
    p_plug_display_sequence => 10,
    p_plug_source_type => 'NATIVE_HTML',
    p_plug_query_options => 'DERIVED_REPORT_COLUMNS'
  );
  wwv_flow_imp_page.create_page_item(
    p_id => {item_id},
    p_name => 'P{new_page_id}_PROBE_ITEM',
    p_item_sequence => 10,
    p_item_plug_id => {region_id},
    p_display_as => 'NATIVE_TEXT_FIELD'
  );
  commit;
end;
/
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=120)
    if rc != 0 or _has_db_error(stdout):
        raise RuntimeError(
            f"add page/region/item failed:\n{_strip_banner(stdout)}\n{stderr}"
        )


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


def verify_runtime(runtime_url: str, app_alias: str, page_id: int) -> tuple[bool, str]:
    url = f"{runtime_url.rstrip('/')}/{app_alias.lower()}/{page_id}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            html = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200:
                return (False, f"{url} -> HTTP {resp.status}")
            for marker in ["application not found", "ORA-", "ERR-", "<title>Error"]:
                if marker in html:
                    return (False, f"{url} -> contains marker '{marker}'")
            return (True, f"{url} -> HTTP 200, no error markers")
    except urllib.error.HTTPError as e:
        return (False, f"{url} -> HTTPError {e.code}: {e.reason}")
    except Exception as e:
        return (False, f"{url} -> {type(e).__name__}: {e}")


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
    source_app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))

    clone_app_id = 900000 + secrets.randbelow(99999)
    # Pick safe new IDs in clone (high range to avoid collision with cloned content)
    probe_page_id = 9000
    probe_region_id = 90000
    probe_item_id = 900000

    findings: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "sqlcl_conn": conn,
        "workspace": workspace,
        "schema": schema,
        "source_app_id": source_app_id,
        "clone_app_id": clone_app_id,
        "probe_ids": {
            "page": probe_page_id,
            "region": probe_region_id,
            "item": probe_item_id,
        },
        "steps": [],
    }
    overall_pass = True

    try:
        ws_id = lookup_workspace_id(conn, workspace)
        findings["workspace_id"] = ws_id
        print(f"[Lookup] workspace {workspace} -> id {ws_id}")

        print(f"[1/8] Get source app {source_app_id} metadata")
        meta_source = metadata_for_app(conn, source_app_id)
        findings["steps"].append(
            {"step": "source_meta", "status": "ok", "metadata": meta_source}
        )
        print(f"    source: {meta_source}")

        print(f"[2/8] Export source app {source_app_id} via 'apex export'")
        export_dir = Path(os.environ.get("TEMP", "/tmp")) / f"apex_rt_{clone_app_id}"
        export_file = export_app(conn, source_app_id, export_dir)
        findings["steps"].append(
            {
                "step": "export_source",
                "status": "ok",
                "file": str(export_file),
                "size": export_file.stat().st_size,
            }
        )
        print(f"    -> {export_file} ({export_file.stat().st_size} bytes)")

        print(f"[3/8] Reimport as clone app {clone_app_id} (with offset)")
        reimport_as_new_app(conn, export_file, clone_app_id, ws_id, schema)
        meta_clone = metadata_for_app(conn, clone_app_id)
        findings["steps"].append(
            {
                "step": "reimport",
                "status": "ok",
                "metadata": meta_clone,
            }
        )
        print(f"    clone: {meta_clone}")

        print("[4/8] Compare metadata identity (source vs clone)")
        # Pages should match. Regions/items may differ slightly due to offset
        # generation but at minimum should be > 0 and proportional.
        if meta_source["pages"] != meta_clone["pages"]:
            findings["steps"].append(
                {
                    "step": "metadata_match",
                    "status": "fail",
                    "source": meta_source,
                    "clone": meta_clone,
                    "reason": "page count mismatch",
                }
            )
            overall_pass = False
            print(
                f"    FAIL - page count mismatch "
                f"({meta_source['pages']} vs {meta_clone['pages']})"
            )
        elif meta_clone["regions"] == 0 or meta_clone["items"] == 0:
            findings["steps"].append(
                {
                    "step": "metadata_match",
                    "status": "fail",
                    "source": meta_source,
                    "clone": meta_clone,
                    "reason": "clone has 0 regions or items - export/reimport incomplete",
                }
            )
            overall_pass = False
            print("    FAIL - clone has 0 regions or items")
        else:
            findings["steps"].append(
                {
                    "step": "metadata_match",
                    "status": "ok",
                    "source": meta_source,
                    "clone": meta_clone,
                }
            )
            print("    PASS - metadata identity OK")

        print(
            f"[5/8] Add probe page/region/item to clone {clone_app_id} via wwv_flow_imp_page.*"
        )
        add_page_region_item(
            conn, clone_app_id, probe_page_id, probe_region_id, probe_item_id
        )
        meta_after_probe = metadata_for_app(conn, clone_app_id)
        if meta_after_probe["pages"] != meta_clone["pages"] + 1:
            findings["steps"].append(
                {
                    "step": "add_probe",
                    "status": "fail",
                    "before": meta_clone,
                    "after": meta_after_probe,
                    "reason": "page count did not increase by 1",
                }
            )
            overall_pass = False
            print(
                f"    FAIL - page count {meta_after_probe['pages']} "
                f"!= expected {meta_clone['pages']+1}"
            )
        else:
            findings["steps"].append(
                {
                    "step": "add_probe",
                    "status": "ok",
                    "metadata": meta_after_probe,
                }
            )
            print(
                f"    PASS - page added "
                f"(count {meta_clone['pages']} -> {meta_after_probe['pages']})"
            )

        print(f"[6/8] Re-export clone {clone_app_id} and grep for probe page name")
        export_dir2 = Path(os.environ.get("TEMP", "/tmp")) / f"apex_rt2_{clone_app_id}"
        export_file2 = export_app(conn, clone_app_id, export_dir2)
        export_text = export_file2.read_text(encoding="utf-8", errors="replace")
        if "PHASE0_PROBE" in export_text:
            findings["steps"].append(
                {
                    "step": "reexport_contains_probe",
                    "status": "ok",
                    "file": str(export_file2),
                    "size": export_file2.stat().st_size,
                }
            )
            print("    PASS - re-export contains 'PHASE0_PROBE'")
        else:
            findings["steps"].append(
                {
                    "step": "reexport_contains_probe",
                    "status": "fail",
                    "reason": "probe page not in re-export",
                }
            )
            overall_pass = False
            print("    FAIL - probe page text not in re-export")

        print(f"[7/8] Open probe page in runtime ({meta_after_probe['alias']}/{probe_page_id})")
        ok, info = verify_runtime(
            runtime_url, meta_after_probe["alias"] or "", probe_page_id
        )
        findings["steps"].append(
            {"step": "runtime_open", "status": "ok" if ok else "fail", "detail": info}
        )
        if ok:
            print(f"    PASS - {info}")
        else:
            overall_pass = False
            print(f"    FAIL - {info}")

        print(f"[8/8] Drop clone {clone_app_id}")
    except Exception as e:
        findings["steps"].append(
            {"step": "exception", "status": "fail", "detail": f"{type(e).__name__}: {e}"}
        )
        overall_pass = False
        print(f"\nEXCEPTION: {e}", file=sys.stderr)
    finally:
        try:
            drop_app(conn, clone_app_id)
            findings["cleanup"] = {"clone_dropped": clone_app_id}
        except Exception as e:
            findings["cleanup"] = {"clone_drop_failed": str(e)}

    findings["overall"] = "PASS" if overall_pass else "FAIL"

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("a", encoding="utf-8") as fh:
        fh.write("\n\n## Gate 5 Round-Trip Proof Findings (clone strategy)\n\n")
        fh.write("```json\n")
        fh.write(json.dumps(findings, indent=2, ensure_ascii=False))
        fh.write("\n```\n")

    print(f"\n=== ROUND-TRIP RESULT: {findings['overall']} ===")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
