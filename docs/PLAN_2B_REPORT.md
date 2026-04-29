# Plan 2B Final Verification Report

**Date**: 2026-04-30
**Plan**: `docs/superpowers/plans/2026-04-29-plan-2b-phase-2-tools.md` (in oracle-apex-skill-builder repo)
**Phase 2 baseline**: tag `mvp-1.0` — Plan 2A direct-write MVP
**Verdict**: ✅ **PASS — proceed to mvp-2.0** (8/8 mini-plans done; 34 tools added + 8 deferred with documented reasoning)

## Tags

| Tag | Scope |
|---|---|
| `mvp-1.0` | Plan 2A direct-write MVP (26 tools, 180 unit tests, 11 live tests) |
| `mvp-2.0-2b1` | 2B-1 page/region/item lifecycle CRUD (8 tools impl + 2 def) |
| `mvp-2.0-2b2` | 2B-2 buttons/processes/DA (5 tools impl + 1 def) |
| `mvp-2.0-2b3` | 2B-3 region types (2 tools impl + 2 def) |
| `mvp-2.0-2b4-2b5` | 2B-4 charts/cards/calendar + 2B-5 shared components (8 tools impl) |
| `mvp-2.0-2b6` | 2B-6 JS/CSS + read extras (4 tools impl + 2 def) |
| `mvp-2.0-2b7` | 2B-7 generators (3 tools impl + 1 def) |
| `mvp-2.0-2b8` | 2B-8 app lifecycle inc. create_app (4 tools impl) |
| **`mvp-2.0`** | **Plan 2B complete: 60+ tools cumulative** |

## Phase 2 mini-plan outcomes

| Mini-plan | Implemented | Deferred | Live verified |
|---|---|---|---|
| 2B-1 page/region/item lifecycle | apex_delete_page, apex_update_page, apex_get_page_details, apex_describe_page_human, apex_list_regions, apex_delete_region, apex_list_items, apex_delete_item, apex_bulk_add_items | apex_copy_page, apex_update_region, apex_update_item | 6/7 |
| 2B-2 buttons/processes/DA | apex_add_button, apex_add_process, apex_list_processes, apex_add_dynamic_action, apex_list_dynamic_actions | apex_delete_button | 3/3 |
| 2B-3 region types | apex_add_form_region, apex_add_interactive_grid (minimal) | apex_add_interactive_report, apex_add_master_detail | 2/2 |
| 2B-4 charts/cards/calendar | apex_add_jet_chart, apex_add_metric_cards, apex_add_calendar | – | 3/3 |
| 2B-5 shared components | apex_add_lov, apex_list_lovs, apex_add_auth_scheme, apex_add_nav_item, apex_add_app_item | – | 7/7 (after isolation fix) |
| 2B-6 JS/CSS + read extras | apex_add_static_app_file, apex_search_objects, apex_dependencies, apex_list_workspace_users | apex_add_page_js, apex_add_app_css | 1/3 (read tools blocked by oracledb pool gap) |
| 2B-7 generators | apex_generate_crud, apex_generate_dashboard, apex_generate_modal_form | apex_generate_login | 3/4 |
| 2B-8 app lifecycle | apex_get_app_details, apex_validate_app, apex_delete_app, **apex_create_app** | – | 2/4 (read tools blocked by oracledb pool gap) |
| **Total Phase 2** | **34 implemented** | **8 deferred** | **27/33 live verified** |

## Architectural findings recorded across Phase 2

1. **APEX 24.2 internal API surface is inconsistent** — many "obvious" procs missing:
   - No `DELETE_BUTTON` proc (not in any package)
   - No `UPDATE_REGION` proc (only EDIT_PAGE_ITEM via app_builder_api)
   - No `UPDATE_FLOW` / `UPDATE_APPLICATION` proc → can't update inline JS/CSS post-create
   - No `REMOVE_LOV` / `REMOVE_AUTHENTICATION` / `REMOVE_FLOW_ITEM` public procs → leftover state must be cleaned via App Builder UI
   - No `COPY_PAGE` proc

2. **Two distinct call conventions** for write procs:
   - `wwv_flow_imp.*` / `wwv_flow_imp_page.*` / `wwv_flow_imp_shared.*` — REQUIRE `wwv_flow_imp.import_begin/import_end` session wrap
   - `wwv_flow_app_builder_api.*` — REQUIRE `apex_240200.` schema prefix + `apex_util.set_workspace` + `set_application_id` preamble (NO import session)

3. **`apex_create_app` works** with curated minimal params from `wwv_flow_imp.create_flow` — verified by full live create+delete round-trip. The proc has 178 args but 0 strictly required; default behavior produces a usable app.

4. **Test isolation requires randomized probe names + ids** — the `WWV_FLOW_ITEMS_IDX3` unique constraint causes name collisions across CI runs. Use `secrets.token_hex(3)` + `secrets.randbelow(99)` for per-run uniqueness.

5. **`page_mode='MODAL'` parameter** flows through `wwv_flow_imp_page.create_page` — extension to `apex_add_page` enables modal form generation.

6. **Generator atomicity is best-effort, not transactional** — each underlying tool opens its own ImportSession (auto-commits per session). On mid-way failure, generators raise `GENERATOR_PARTIAL` with `metadata.created` listing what succeeded; user must manually clean up.

7. **Static app files limited to ~30KB inline-text** — chunked LOB construction needed for bigger CSS/JS. Phase 3 follow-up.

8. **Read-tool oracledb pool gap persists** — 4 read tools (apex_list_lovs, apex_search_objects, apex_dependencies, apex_list_workspace_users; plus apex_get_app_details and apex_validate_app from 2B-8) currently use `_get_pool()` which is empty under `auth_mode=sqlcl`. They skip cleanly in live tests but block real-world use under sqlcl-only profile. Plan 2A pool-gap fix addressed write tools; read tools need similar SQLcl-subprocess fallback.

## Test counts

- **Unit tests**: 328 passed (was 180 at mvp-1.0; +148 across Plan 2B)
- **Live integration tests**: 35+ executed; ~27 PASS, 4-6 SKIP (oracledb pool gap), 0 FAIL
- **ruff + mypy**: clean at every commit (59+ source files)

## Deferred tools — reasoning

| Tool | Reason | Future path |
|---|---|---|
| apex_copy_page | No `WWV_FLOW_APP_BUILDER_API.COPY_PAGE` or equivalent proc found | Phase 3: read source page, replicate via add_page + add_region + add_item composition |
| apex_update_region | No native `UPDATE_REGION` proc | Phase 3: workaround via delete_region + add_region |
| apex_update_item | `wwv_flow_imp.update_page_item` requires all `default=N` params; `EDIT_PAGE_ITEM` requires reading all attributes first | Phase 3: read-then-update composition |
| apex_delete_button | No `REMOVE_PAGE_BUTTON` proc anywhere | Phase 3: investigate direct DML via DBA (risky) or delete_page cascade |
| apex_add_interactive_report | `create_worksheet` + per-column `create_worksheet_column` requires SQL column-name discovery (parse AST or execute) | Phase 3: SQL parsing helper |
| apex_add_master_detail | Requires both IGs + `filtered_region_id` / column-link metadata; depends on stable IG infrastructure | Phase 3: after IG hardening |
| apex_add_page_js | No `UPDATE_PAGE` or `UPDATE_FLOW` proc accepts `p_javascript_code` post-create | Phase 3: workaround via apex_add_static_app_file (page-bound JS file) + page link |
| apex_add_app_css | Same as page_js | Phase 3: app-level static file approach |
| apex_generate_login | Login page composes USERNAME/PASSWORD items + Login button + `apex_authentication.login` process + auth-scheme wiring; each is its own MVP-deferred surface | Phase 3 or App Builder UI "Create > Login Page" wizard |

## Repo

- GitHub: https://github.com/ds-mrtq/apex-builder-mcp
- Path: `D:\repos\apex-builder-mcp`
- Commits since `mvp-1.0`: ~14
- LOC: ~5500 Python (production) + tests

## Out of scope for `mvp-2.0`

- **2B-9 Design System bridge** — apply DS spec → Theme Style + Custom CSS (USP feature per spec)
- **2B-10 PROD arm** — sandbox PROD-clone with allowlist + backup-before-write + rollback (power-user feature)
- **Read-tool sqlcl-fallback** — fix oracledb pool gap for 4-6 read tools blocked under sqlcl-only auth
- **Phase 3 polish** — retry deferred tools as APEX patches add native procs; chunked LOB for large static files; SQL parser for IR column discovery

## Next-step recommendations (priority-ordered)

1. **Battle-test mvp-2.0 in real Vicem APEX projects** — Plan 2B was speculative scope; real workflow will reveal which tools matter most and which are over-engineered
2. **Read-tool sqlcl-fallback** — closes a known gap; ~30 min effort similar to Plan 2A pool-gap fix
3. **2B-9 Design System bridge** — restores USP feature deferred from MVP planning
4. **Polish deferred tools** as APEX 24.2.X patches surface new procs (OR document workarounds in skill)
5. **2B-10 PROD arm** — sandbox PROD-clone allowlist, only after read-tool gap closed and 6+ months of DEV usage
