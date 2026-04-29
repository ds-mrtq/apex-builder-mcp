# Phase 0 Verification Report

**Date**: 2026-04-29
**Spec**: `docs/superpowers/specs/2026-04-28-oracle-apex-toolkit-design.md` (revision v0.2) [in oracle-apex-skill-builder repo]
**Plan**: `docs/superpowers/plans/2026-04-28-phase-0-foundation-roundtrip-gate.md` [in oracle-apex-skill-builder repo]
**Verdict**: ✅ **PASS — proceed to Plan 2A: Direct-Write MVP**

**Test environment**:
- DB DSN: `ebstest.vicemhatien.vn:1522/TEST1` (Vicem Hà Tiên TEST env)
- APEX: 24.2.12 (workspace EREPORT, id 100002)
- DB user: `ereport` (via SQLcl saved connection `ereport_test8001`)
- Test app: `100` Data Loading (25 pages, 66 regions, 41 items, alias DATA-LOADING)
- Runtime URL: `https://apexdev.vicemhatien.com.vn/ords/r/ereport`
- Python: 3.14.4
- FastMCP: 3.2.4
- python-oracledb: 3.4.2
- SQLcl: 26.1

## Gate outcomes

| Gate | Status | Notes |
|---|---|---|
| 1 — FastMCP tools/list_changed | ✅ PASS (server-side) | Verified by `test_entrypoint::test_load_category_registers_tools_with_server`. Manual CLI verification in Claude Code + Codex still pending (non-blocking) |
| 2 — Sample APEX procs callable | ✅ PASS (folded into Gate 5) | `wwv_flow_imp_page.create_page/plug/item` and `remove_page` all verified in Gate 5 step 5 |
| 3 — Win Credential Manager round-trip | ✅ PASS | `tests/integration/test_keyring_real.py` — set/get/delete cycle works |
| 4 — SQLcl metadata reader | ⚠️ PARTIAL | VS Code Extension JSON format reader works (5 unit tests). SQLcl 26 uses proprietary store at `~/AppData/Roaming/SQLcl/` — Plan 2A follow-up: add `connmgr show <name>` subprocess fallback. Connection metadata for ereport_test8001 already extracted via direct `connmgr show` |
| 5 — Round-Trip Proof | ✅ PASS | All 7 steps green; see findings JSON below |

## Architectural findings (must inform Plan 2A)

1. **`wwv_flow_imp_page.create_*` requires APEX import session context** — wrap individual calls in `wwv_flow_imp.import_begin(p_version_yyyy_mm_dd, p_release='24.2.12', p_default_workspace_id, p_default_application_id, p_default_id_offset=0, p_default_owner)` and `wwv_flow_imp.import_end(p_auto_install_sup_obj => nvl(wwv_flow_application_install.get_auto_install_sup_obj, false))` + `commit`. Without import_begin, `g_security_group_id` is unset → ORA-20001 from WWV_IMP_UTIL line 142.
2. **Cleanup proc `wwv_flow_imp_page.remove_page(p_flow_id, p_page_id)`** also requires import session wrap (same pattern).
3. **App creation is OUT OF SCOPE for MVP** — `wwv_flow_imp.create_application` does NOT exist; the actual proc is `wwv_flow_imp.create_flow` with 100+ params (impractical for direct calls). MVP write tools (`apex_add_page/region/item`) only ADD to existing apps; this is correct posture.
4. **Clone-via-`apex_application_install.generate_offset` is FRAGILE** for apps with shared component dependencies — failed on app 100 with `ORA-02291: WWV_FLOW_NAVBAR_TEMPLATE_FK violated`. This validates the user's existing `oracle-apex` skill knowledge ("broken FK during re-import"). MVP should avoid offset-based reimport for full apps; prefer in-place mutation.
5. **Runtime URL pattern** verified: `<runtime_url>/<workspace_path_prefix_lowercased>/<app_alias_lowercased>/<page_id_or_alias>`. App 100 alias = `DATA-LOADING` → `/data-loading/8000`.
6. **nginx in front of ORDS rejects requests without browser User-Agent** (returns HTTP 410 Gone universally). Plan 2A's runtime checks must include browser UA header.
7. **APEX runtime auth-protected pages** return HTTP 302 → `/login` or `/sign-in` for unauthenticated requests. Treat 302 to login as "page registered with ORDS" (positive signal). Don't follow auth redirects without cookie jar (causes infinite loop).
8. **Minimum page params for ORDS-registered runtime page**: `p_id`, `p_name`, `p_alias`, `p_step_title`, `p_autocomplete_on_off='OFF'`, `p_page_template_options='#DEFAULT#'`. Sufficient for ORDS to recognize the page; full UI rendering requires more (template_id, ui_id, etc.) — Plan 2A's `apex_add_page` should expose params for both modes.
9. **SQLcl saved connections** (`sql -name <conn>`) are the cleanest auth path — same UX as SQLcl MCP. Plan 2A should support this auth mode in addition to (or in place of) explicit user/password.

## Decision rule (per spec section 9 auto-pivot)

- All 5 gates PASS or PARTIAL with documented follow-up → **Plan 2A: Direct-Write MVP** ← **WE ARE HERE**
- Any FAIL → Plan 2B (file-based pivot)

**This run's decision**: **Plan 2A — Direct-Write MVP**

Plan 2A first-task scope (informed by findings 1-9 above):
- Implement `apex_add_page/region/item` tools that wrap calls in `wwv_flow_imp.import_begin/import_end` automatically
- Implement `apex_delete_page` similarly wrapping `remove_page`
- Add SQLcl saved-connection auth mode (use `sql -name <conn>` subprocess for auth)
- Add `connmgr show <name>` subprocess fallback to T7's metadata reader for SQLcl 26 store format
- Default page param coverage: minimum-viable + extended modes
- Runtime check helper accepts 302→login as success

---

[Gate-specific findings appended below as they run]


## Gate 5 Round-Trip Proof Findings (SQLcl-based)

```json
{
  "timestamp": "2026-04-28T15:43:58.091776+00:00",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "steps": [
    {
      "step": "exception",
      "status": "fail",
      "detail": "'charmap' codec can't encode character '\\u2192' in position 27: character maps to <undefined>"
    }
  ],
  "workspace_id": 100002,
  "overall": "FAIL"
}
```


## Gate 5 Round-Trip Proof Findings (clone strategy)

```json
{
  "timestamp": "2026-04-28T17:11:48.045903+00:00",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "source_app_id": 100,
  "clone_app_id": 960441,
  "probe_ids": {
    "page": 9000,
    "region": 90000,
    "item": 900000
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "export_source",
      "status": "ok",
      "file": "C:\\Users\\nguye\\AppData\\Local\\Temp\\apex_rt_960441\\f100.sql",
      "size": 589039
    },
    {
      "step": "exception",
      "status": "fail",
      "detail": "RuntimeError: reimport failed:\n--application/set_environment\nAPPLICATION 100 - Data Loading\n--application/delete_application\n--application/create_application\n--application/user_interfaces\n--application/shared_components/navigation/lists/desktop_navigation_menu\n--application/shared_components/navigation/lists/desktop_navigation_bar\n--application/shared_components/navigation/lists/application_configuration\n--application/shared_components/navigation/lists/user_interface\n--application/shared_components/navigation/lists/activity_reports\n--application/shared_components/navigation/lists/access_control\n--application/shared_components/navigation/lists/feedback\n--application/shared_components/navigation/lists/data_load_wizard_progress_load_price_list\n--application/shared_components/navigation/listentry\n--application/shared_components/files/app_icon_svg\n--application/shared_components/files/app_icon_css\n--application/shared_components/files/banggia_template_xlsx\n--application/plugin_settings\n--application/shared_components/security/authorizations/is_bang_gia_manager\n--application/shared_components/security/app_access_control/administrator\n--application/shared_components/security/app_access_control/contributor\n--application/shared_components/security/app_access_control/reader\n--application/shared_components/security/app_access_control/bang_gia_manager\n--application/shared_components/navigation/navigation_bar\n--application/shared_components/logic/application_settings\n--application/shared_components/navigation/tabs/standard\n--application/shared_components/navigation/tabs/parent\n--application/shared_components/user_interface/lovs/desktop_theme_styles\n--application/shared_components/user_interface/lovs/feedback_rating\n--application/shared_components/user_interface/lovs/feedback_status\n--application/shared_components/user_interface/lovs/timeframe_4_weeks\n--application/shared_components/user_interface/lovs/user_theme_preference\n--application/shared_components/user_interface/lovs/view_as_report_chart\n--application/pages/page_groups\n--application/shared_components/navigation/breadcrumbs/breadcrumb\n--application/shared_components/navigation/breadcrumbentry\n--application/shared_components/user_interface/templates/page/left_side_column\n--application/shared_components/user_interface/templates/page/left_and_right_side_columns\n--application/shared_components/user_interface/templates/page/login\n--application/shared_components/user_interface/templates/page/master_detail\n--application/shared_components/user_interface/templates/page/modal_dialog\n--application/shared_components/user_interface/templates/page/right_side_column\n--application/shared_components/user_interface/templates/page/wizard_modal_dialog\n--application/shared_components/user_interface/templates/page/standard\n--application/shared_components/user_interface/templates/page/minimal_no_navigation\n--application/shared_components/user_interface/templates/list/side_navigation_menu\n--application/shared_components/user_interface/templates/popuplov\n--application/shared_components/user_interface/themes\n--application/shared_components/user_interface/theme_style\n--application/shared_components/user_interface/theme_files\n--application/shared_components/user_interface/template_opt_groups\n--application/shared_components/user_interface/template_options\n--application/shared_components/globalization/language\n--application/shared_components/logic/build_options\n--application/shared_components/globalization/messages\n--application/shared_components/globalization/dyntranslations\n--application/user_interfaces/combined_files\n--application/pages/page_00000\n--application/pages/page_00001\n--application/pages/page_00002\n--application/pages/page_09999\n--application/pages/page_10000\n--application/pages/page_10010\n--application/pages/page_10020\n--application/pages/page_10030\n--application/pages/page_10031\n--application/pages/page_10032\n--application/pages/page_10033\n--application/pages/page_10034\n--application/pages/page_10035\n--application/pages/page_10036\n--application/pages/page_10040\n--application/pages/page_10041\n--application/pages/page_10042\n--application/pages/page_10043\n--application/pages/page_10044\n--application/pages/page_10050\n--application/pages/page_10051\n--application/pages/page_10053\n--application/pages/page_10054\n--application/pages/page_10060\n--application/pages/page_10061\n--application/deployment/definition\n--application/deployment/checks\n--application/deployment/buildoptions\n--application/end_environment\nbegin\n*\nERROR at line 1:\nORA-02091: transaction rolled back\nORA-02291: integrity constraint (APEX_240200.WWV_FLOW_NAVBAR_TEMPLATE_FK) violated - parent key not found\nORA-06512: at \"APEX_240200.WWV_FLOW_SECURITY\", line 2217\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP\", line 1281\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP\", line 1308\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP\", line 1348\nORA-06512: at line 2\nhttps://docs.oracle.com/error-help/db/ora-02091/\n"
    }
  ],
  "workspace_id": 100002,
  "cleanup": {
    "clone_dropped": 960441
  },
  "overall": "FAIL"
}
```


## Gate 5 In-Place Probe Findings (Option C)

```json
{
  "timestamp": "2026-04-29T01:40:55.857503+00:00",
  "strategy": "in-place probe (Option C)",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "app_id": 100,
  "probe_ids": {
    "page": 8000,
    "region": 8001,
    "item": 8002
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "exception",
      "status": "fail",
      "detail": "RuntimeError: add probe failed:\nbegin\n*\nERROR at line 1:\nORA-20001: call=wwv_flow_imp_page.create_page, id=8000, component=PHASE0_PROBE, sqlerrm=ORA-20001: Package variable g_security_group_id must be set.\nORA-06512: at \"APEX_240200.WWV_IMP_UTIL\", line 142\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP_PAGE\", line 144\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP_PAGE\", line 1823\nORA-20001: Package variable g_security_group_id must be set.\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP\", line 109\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP\", line 145\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP_PAGE\", line 1459\nORA-06512: at line 5\nhttps://docs.oracle.com/error-help/db/ora-20001/\nMore Details :\nhttps://docs.oracle.com/error-help/db/ora-20001/\nhttps://docs.oracle.com/error-help/db/ora-06512/\nstderr:\n"
    }
  ],
  "workspace_id": 100002,
  "overall": "FAIL"
}
```


## Gate 5 In-Place Probe Findings (Option C)

```json
{
  "timestamp": "2026-04-29T01:45:14.696379+00:00",
  "strategy": "in-place probe (Option C)",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "app_id": 100,
  "probe_ids": {
    "page": 8000,
    "region": 8001,
    "item": 8002
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "add_probe",
      "status": "ok",
      "metadata": {
        "pages": 26,
        "regions": 67,
        "items": 42,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "export",
      "status": "ok",
      "file": "C:\\Users\\nguye\\AppData\\Local\\Temp\\apex_phase0_100\\f100.sql",
      "size": 589802
    },
    {
      "step": "export_contains_probe",
      "status": "ok"
    },
    {
      "step": "runtime_open",
      "status": "fail",
      "detail": "https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/8000 -> HTTPError 410: Gone"
    },
    {
      "step": "remove_probe",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "final_integrity",
      "status": "ok"
    }
  ],
  "workspace_id": 100002,
  "overall": "FAIL"
}
```


## Gate 5 In-Place Probe Findings (Option C)

```json
{
  "timestamp": "2026-04-29T03:02:19.601544+00:00",
  "strategy": "in-place probe (Option C)",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "app_id": 100,
  "probe_ids": {
    "page": 8000,
    "region": 8001,
    "item": 8002
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "add_probe",
      "status": "ok",
      "metadata": {
        "pages": 26,
        "regions": 67,
        "items": 42,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "export",
      "status": "ok",
      "file": "C:\\Users\\nguye\\AppData\\Local\\Temp\\apex_phase0_100\\f100.sql",
      "size": 589865
    },
    {
      "step": "export_contains_probe",
      "status": "ok"
    },
    {
      "step": "runtime_open",
      "status": "fail",
      "detail": "https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/8000 -> HTTPError 410: Gone"
    },
    {
      "step": "remove_probe",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "final_integrity",
      "status": "ok"
    }
  ],
  "workspace_id": 100002,
  "overall": "FAIL"
}
```


## Gate 5 In-Place Probe Findings (Option C)

```json
{
  "timestamp": "2026-04-29T03:10:00.567808+00:00",
  "strategy": "in-place probe (Option C)",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "app_id": 100,
  "probe_ids": {
    "page": 8000,
    "region": 8001,
    "item": 8002
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 26,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "exception",
      "status": "fail",
      "detail": "RuntimeError: add probe failed:\nPL/SQL procedure successfully completed.\nRollback\nbegin\n*\nERROR at line 1:\nORA-20001: call=wwv_flow_imp_page.create_page, id=8000, component=PHASE0_PROBE, sqlerrm=ORA-00001: unique constraint (APEX_240200.WWV_FLOW_STEPS_PK) violated\nORA-06512: at \"APEX_240200.WWV_IMP_UTIL\", line 142\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP_PAGE\", line 144\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP_PAGE\", line 1823\nORA-00001: unique constraint (APEX_240200.WWV_FLOW_STEPS_PK) violated\nORA-06512: at \"APEX_240200.WWV_FLOW_IMP_PAGE\", line 1591\nORA-06512: at line 2\nhttps://docs.oracle.com/error-help/db/ora-20001/\nMore Details :\nhttps://docs.oracle.com/error-help/db/ora-20001/\nhttps://docs.oracle.com/error-help/db/ora-06512/\nhttps://docs.oracle.com/error-help/db/ora-00001/\nstderr:\n"
    }
  ],
  "workspace_id": 100002,
  "overall": "FAIL"
}
```


## Gate 5 In-Place Probe Findings (Option C)

```json
{
  "timestamp": "2026-04-29T03:10:56.480153+00:00",
  "strategy": "in-place probe (Option C)",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "app_id": 100,
  "probe_ids": {
    "page": 8000,
    "region": 8001,
    "item": 8002
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "add_probe",
      "status": "ok",
      "metadata": {
        "pages": 26,
        "regions": 67,
        "items": 42,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "export",
      "status": "ok",
      "file": "C:\\Users\\nguye\\AppData\\Local\\Temp\\apex_phase0_100\\f100.sql",
      "size": 589865
    },
    {
      "step": "export_contains_probe",
      "status": "ok"
    },
    {
      "step": "runtime_open",
      "status": "fail",
      "detail": "https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/8000 -> HTTPError 302: The HTTP server returned a redirect error that would lead to an infinite loop.\nThe last 30x error message was:\nMoved Temporarily"
    },
    {
      "step": "remove_probe",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "final_integrity",
      "status": "ok"
    }
  ],
  "workspace_id": 100002,
  "overall": "FAIL"
}
```


## Gate 5 In-Place Probe Findings (Option C)

```json
{
  "timestamp": "2026-04-29T03:13:38.769870+00:00",
  "strategy": "in-place probe (Option C)",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "app_id": 100,
  "probe_ids": {
    "page": 8000,
    "region": 8001,
    "item": 8002
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "add_probe",
      "status": "ok",
      "metadata": {
        "pages": 26,
        "regions": 67,
        "items": 42,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "export",
      "status": "ok",
      "file": "C:\\Users\\nguye\\AppData\\Local\\Temp\\apex_phase0_100\\f100.sql",
      "size": 589865
    },
    {
      "step": "export_contains_probe",
      "status": "ok"
    },
    {
      "step": "runtime_open",
      "status": "ok",
      "detail": "https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/8000 -> 302 -> https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/login?session=2763249275160 (auth redirect = page registered)"
    },
    {
      "step": "remove_probe",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "final_integrity",
      "status": "ok"
    }
  ],
  "workspace_id": 100002,
  "overall": "PASS"
}
```


## Gate 5 In-Place Probe Findings (Option C)

```json
{
  "timestamp": "2026-04-29T05:05:53.226283+00:00",
  "strategy": "in-place probe (Option C)",
  "sqlcl_conn": "ereport_test8001",
  "workspace": "EREPORT",
  "schema": "EREPORT",
  "app_id": 100,
  "probe_ids": {
    "page": 8000,
    "region": 8001,
    "item": 8002
  },
  "steps": [
    {
      "step": "source_meta",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "add_probe",
      "status": "ok",
      "metadata": {
        "pages": 26,
        "regions": 67,
        "items": 42,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "export",
      "status": "ok",
      "file": "C:\\Users\\nguye\\AppData\\Local\\Temp\\apex_phase0_100\\f100.sql",
      "size": 589865
    },
    {
      "step": "export_contains_probe",
      "status": "ok"
    },
    {
      "step": "runtime_open",
      "status": "ok",
      "detail": "https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/8000 -> 302 -> https://apexdev.vicemhatien.com.vn/ords/r/ereport/data-loading/login?session=9219184856052 (auth redirect = page registered)"
    },
    {
      "step": "remove_probe",
      "status": "ok",
      "metadata": {
        "pages": 25,
        "regions": 66,
        "items": 41,
        "alias": "DATA-LOADING"
      }
    },
    {
      "step": "final_integrity",
      "status": "ok"
    }
  ],
  "workspace_id": 100002,
  "overall": "PASS"
}
```
