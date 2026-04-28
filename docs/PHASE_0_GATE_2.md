# Gate 2: oracledb thin + 5 sample WWV_FLOW_IMP_PAGE calls

## Run

```bash
read -sp "Password for ereport: " APEX_TEST_PASSWORD ; export APEX_TEST_PASSWORD ; echo
export APEX_TEST_DSN="ebstest.vicemhatien.vn:1522/TEST1"
export APEX_TEST_USER="ereport"
export APEX_TEST_WORKSPACE_ID="<numeric>"
export APEX_TEST_SCHEMA="EREPORT"

cd /d/repos/apex-builder-mcp
./.venv/Scripts/pytest.exe tests/integration/test_wwv_calls_real.py -v --integration
```

## Pass criteria

- All 5 sample calls executed without OCI errors:
  - `wwv_flow_imp_page.create_page`
  - `wwv_flow_imp_page.create_page_plug`
  - `wwv_flow_imp_page.create_page_item`
  - `wwv_flow_imp_page.create_page_button`
  - `wwv_flow_imp_page.create_page_process`
- Sandbox app created + region count >= 1 verified
- Cleanup `remove_flow` succeeded

## On FAIL

Document each failed call (ORA code + line). If `wwv_flow_imp_page.create_page` itself fails, MVP cannot proceed with direct write → triggers spec auto-pivot rule (Plan 2B).
