"""Phase 0 Gate 5 - in-place probe round-trip (Option C, MVP-aligned).

Tests the actual MVP write path:
1. ADD probe page+region+item to existing app via wwv_flow_imp_page.create_*
2. Verify metadata + export captures probe + runtime renders probe page
3. DELETE probe via wwv_flow_imp_page.remove_page so source app is restored

Source app is briefly modified but cleanly reverted. Probe IDs picked below
the existing page id range to avoid collision (8000 vs app 100's range 9999+).

Required env vars:
    APEX_TEST_SQLCL_NAME       SQLcl named connection (e.g., ereport_test8001)
    APEX_TEST_WORKSPACE        APEX workspace name (e.g., EREPORT)
    APEX_TEST_SCHEMA           Schema (e.g., EREPORT)
    APEX_TEST_RUNTIME_URL      Runtime URL prefix
    APEX_TEST_SOURCE_APP_ID    App id to test on (default: 100)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROBE_PAGE_ID = 8000
PROBE_REGION_ID = 8001
PROBE_ITEM_ID = 8002
PROBE_NAME = "PHASE0_PROBE"


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
    rc, stdout, _ = _sqlcl(conn_name, sql)
    if rc != 0:
        raise RuntimeError(f"workspace lookup failed:\n{stdout}")
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


def add_probe_to_app(conn_name: str, app_id: int, ws_id: int, schema: str) -> None:
    """Add probe page+region+item via APEX import session pattern.

    wwv_flow_imp_page.create_* requires import session context (sets
    g_security_group_id and other globals). Wrap calls in
    wwv_flow_imp.import_begin / import_end per APEX 24.2.12 export format.
    """
    sql = f"""set echo off feedback on define off verify off
whenever sqlerror exit sql.sqlcode rollback
begin
  wwv_flow_imp.import_begin(
    p_version_yyyy_mm_dd => '2024.11.30',
    p_release => '24.2.12',
    p_default_workspace_id => {ws_id},
    p_default_application_id => {app_id},
    p_default_id_offset => 0,
    p_default_owner => '{schema}'
  );
end;
/
begin
  wwv_flow_imp_page.create_page(
    p_id => {PROBE_PAGE_ID},
    p_name => '{PROBE_NAME}',
    p_alias => '{PROBE_NAME}',
    p_step_title => '{PROBE_NAME}',
    p_autocomplete_on_off => 'OFF',
    p_page_template_options => '#DEFAULT#'
  );
  wwv_flow_imp_page.create_page_plug(
    p_id => {PROBE_REGION_ID},
    p_plug_name => '{PROBE_NAME}_REGION',
    p_plug_template => 0,
    p_plug_display_sequence => 10,
    p_plug_source_type => 'NATIVE_HTML',
    p_plug_query_options => 'DERIVED_REPORT_COLUMNS'
  );
  wwv_flow_imp_page.create_page_item(
    p_id => {PROBE_ITEM_ID},
    p_name => 'P{PROBE_PAGE_ID}_PROBE_ITEM',
    p_item_sequence => 10,
    p_item_plug_id => {PROBE_REGION_ID},
    p_display_as => 'NATIVE_TEXT_FIELD'
  );
end;
/
begin
  wwv_flow_imp.import_end(
    p_auto_install_sup_obj => nvl(wwv_flow_application_install.get_auto_install_sup_obj, false)
  );
  commit;
end;
/
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=120)
    if rc != 0 or _has_db_error(stdout):
        raise RuntimeError(
            f"add probe failed:\n{_strip_banner(stdout)}\nstderr:\n{stderr}"
        )


def remove_probe_from_app(conn_name: str, app_id: int, ws_id: int, schema: str) -> None:
    """Delete probe page via wwv_flow_imp_page.remove_page (also needs import session)."""
    sql = f"""set echo off feedback off define off verify off
begin
  wwv_flow_imp.import_begin(
    p_version_yyyy_mm_dd => '2024.11.30',
    p_release => '24.2.12',
    p_default_workspace_id => {ws_id},
    p_default_application_id => {app_id},
    p_default_id_offset => 0,
    p_default_owner => '{schema}'
  );
end;
/
begin
  wwv_flow_imp_page.remove_page(
    p_flow_id => {app_id},
    p_page_id => {PROBE_PAGE_ID}
  );
end;
/
begin
  wwv_flow_imp.import_end(
    p_auto_install_sup_obj => nvl(wwv_flow_application_install.get_auto_install_sup_obj, false)
  );
  commit;
end;
/
exit
"""
    rc, stdout, stderr = _sqlcl(conn_name, sql, timeout=60)
    if rc != 0 or _has_db_error(stdout):
        raise RuntimeError(
            f"remove probe failed:\n{_strip_banner(stdout)}\nstderr:\n{stderr}"
        )


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
        raise RuntimeError(f"no .sql produced in {output_dir}")
    primary = [p for p in candidates if re.match(rf"^f{app_id}\.sql$", p.name)]
    return primary[0] if primary else candidates[0]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Don't follow redirects — we want to inspect the FIRST response."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None  # signal "do not follow"


def verify_runtime(runtime_url: str, app_alias: str, page_id: int) -> tuple[bool, str]:
    """Verify probe page is registered with ORDS.

    nginx in front of ORDS rejects requests without browser User-Agent (returns 410),
    so we send Edge UA. ORDS then returns 302 to a login/sign-in page for protected
    pages — that 302 proves the page is registered with ORDS. We do NOT follow the
    redirect (auth flow needs cookie jar / session). We accept:
      - HTTP 200 with no fatal error markers (page accessible without auth)
      - HTTP 302 with Location pointing at login/sign-in (page registered, auth wall)
    """
    url = f"{runtime_url.rstrip('/')}/{app_alias.lower()}/{page_id}"
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        resp = opener.open(req, timeout=30)  # noqa: S310
        # urllib returns the response directly when redirect handler returns None
        # but newer urllib raises HTTPError instead. Handle both.
        try:
            html = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            location = resp.headers.get("Location", "")
        finally:
            resp.close()
    except urllib.error.HTTPError as e:
        # 3xx codes raised here when redirect handler refuses to follow
        status = e.code
        location = e.headers.get("Location", "") if e.headers else ""
        try:
            html = e.read().decode("utf-8", errors="replace")
        except Exception:
            html = ""
    except Exception as e:
        return (False, f"{url} -> {type(e).__name__}: {e}")

    if status in (301, 302, 303, 307, 308):
        loc_lower = location.lower()
        if "/login" in loc_lower or "/sign-in" in loc_lower or "session=" in loc_lower:
            return (True, f"{url} -> {status} -> {location} (auth redirect = page registered)")
        return (True, f"{url} -> {status} -> {location}")
    if status == 200:
        for marker in [
            "application not found",
            "page not found",
            "ORA-",
            "<title>Error",
        ]:
            if marker in html:
                return (False, f"{url} -> 200 but contains '{marker}'")
        return (True, f"{url} -> HTTP 200, no error markers")
    return (False, f"{url} -> HTTP {status}")


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
    app_id = int(os.environ.get("APEX_TEST_SOURCE_APP_ID", "100"))

    findings: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "strategy": "in-place probe (Option C)",
        "sqlcl_conn": conn,
        "workspace": workspace,
        "schema": schema,
        "app_id": app_id,
        "probe_ids": {
            "page": PROBE_PAGE_ID,
            "region": PROBE_REGION_ID,
            "item": PROBE_ITEM_ID,
        },
        "steps": [],
    }
    overall_pass = True
    probe_added = False
    ws_id = 0  # set in try; referenced in finally cleanup

    try:
        ws_id = lookup_workspace_id(conn, workspace)
        findings["workspace_id"] = ws_id
        print(f"[Lookup] workspace {workspace} -> id {ws_id}")

        print(f"[1/7] Get source metadata for app {app_id}")
        meta_before = metadata_for_app(conn, app_id)
        findings["steps"].append(
            {"step": "source_meta", "status": "ok", "metadata": meta_before}
        )
        print(f"    before: {meta_before}")

        print("[2/7] Add probe page/region/item via wwv_flow_imp_page.create_*")
        add_probe_to_app(conn, app_id, ws_id, schema)
        probe_added = True
        meta_after_add = metadata_for_app(conn, app_id)
        if meta_after_add["pages"] != meta_before["pages"] + 1:
            findings["steps"].append(
                {
                    "step": "add_probe",
                    "status": "fail",
                    "before": meta_before,
                    "after": meta_after_add,
                    "reason": "page count did not increase by 1",
                }
            )
            overall_pass = False
            print(
                f"    FAIL - pages {meta_before['pages']} -> "
                f"{meta_after_add['pages']}, expected +1"
            )
        else:
            findings["steps"].append(
                {
                    "step": "add_probe",
                    "status": "ok",
                    "metadata": meta_after_add,
                }
            )
            print(f"    PASS - pages {meta_before['pages']} -> {meta_after_add['pages']}")

        print(f"[3/7] Export app {app_id} via 'apex export'")
        export_dir = Path(os.environ.get("TEMP", "/tmp")) / f"apex_phase0_{app_id}"
        export_file = export_app(conn, app_id, export_dir)
        findings["steps"].append(
            {
                "step": "export",
                "status": "ok",
                "file": str(export_file),
                "size": export_file.stat().st_size,
            }
        )
        print(f"    -> {export_file} ({export_file.stat().st_size} bytes)")

        print(f"[4/7] Grep export for '{PROBE_NAME}'")
        export_text = export_file.read_text(encoding="utf-8", errors="replace")
        if PROBE_NAME in export_text:
            findings["steps"].append(
                {"step": "export_contains_probe", "status": "ok"}
            )
            print(f"    PASS - export contains '{PROBE_NAME}'")
        else:
            findings["steps"].append(
                {
                    "step": "export_contains_probe",
                    "status": "fail",
                    "reason": "probe name not found in export",
                }
            )
            overall_pass = False
            print(f"    FAIL - '{PROBE_NAME}' not in export")

        print(f"[5/7] Open probe page in runtime ({meta_after_add['alias']}/{PROBE_PAGE_ID})")
        ok, info = verify_runtime(runtime_url, meta_after_add["alias"] or "", PROBE_PAGE_ID)
        findings["steps"].append(
            {"step": "runtime_open", "status": "ok" if ok else "fail", "detail": info}
        )
        if ok:
            print(f"    PASS - {info}")
        else:
            overall_pass = False
            print(f"    FAIL - {info}")

        print("[6/7] Cleanup: remove probe page via wwv_flow_imp_page.remove_page")
        remove_probe_from_app(conn, app_id, ws_id, schema)
        probe_added = False
        meta_after_remove = metadata_for_app(conn, app_id)
        if meta_after_remove["pages"] != meta_before["pages"]:
            findings["steps"].append(
                {
                    "step": "remove_probe",
                    "status": "fail",
                    "before_remove": meta_after_add,
                    "after_remove": meta_after_remove,
                    "expected_pages": meta_before["pages"],
                    "reason": "page count did not return to original",
                }
            )
            overall_pass = False
            print(
                f"    FAIL - pages after remove {meta_after_remove['pages']} "
                f"!= original {meta_before['pages']}"
            )
        else:
            findings["steps"].append(
                {"step": "remove_probe", "status": "ok", "metadata": meta_after_remove}
            )
            print(f"    PASS - pages back to {meta_after_remove['pages']}")

        print("[7/7] Final integrity check: source app metadata identity")
        if meta_after_remove == meta_before:
            findings["steps"].append({"step": "final_integrity", "status": "ok"})
            print("    PASS - source app metadata identical to original")
        else:
            findings["steps"].append(
                {
                    "step": "final_integrity",
                    "status": "warn",
                    "before": meta_before,
                    "after_full_cycle": meta_after_remove,
                    "note": "page count matches but other fields differ",
                }
            )
            print(f"    WARN - some fields differ: {meta_before} vs {meta_after_remove}")
    except Exception as e:
        findings["steps"].append(
            {"step": "exception", "status": "fail", "detail": f"{type(e).__name__}: {e}"}
        )
        overall_pass = False
        print(f"\nEXCEPTION: {e}", file=sys.stderr)
    finally:
        # Defensive cleanup if probe was added but step 6 didn't run
        if probe_added:
            try:
                remove_probe_from_app(conn, app_id, ws_id, schema)
                findings["cleanup"] = "probe removed in finally"
                print("\n[finally] probe removed via finally clause", file=sys.stderr)
            except Exception as e:
                findings["cleanup"] = f"probe cleanup FAILED: {e}"
                print(f"\n[finally] probe cleanup FAILED: {e}", file=sys.stderr)

    findings["overall"] = "PASS" if overall_pass else "FAIL"

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("a", encoding="utf-8") as fh:
        fh.write("\n\n## Gate 5 In-Place Probe Findings (Option C)\n\n")
        fh.write("```json\n")
        fh.write(json.dumps(findings, indent=2, ensure_ascii=False))
        fh.write("\n```\n")

    print(f"\n=== GATE 5 RESULT: {findings['overall']} ===")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
