# Gate 5: Round-Trip Proof (the deciding gate)

## Goal

Prove that an app built via internal `WWV_FLOW_IMP_PAGE` calls round-trips correctly:
1. Public-API export captures all metadata
2. Re-import reconstructs metadata identically
3. Resulting page opens at runtime without error

If ANY of those 3 fail → MVP pivots to file-based (Plan 2B).

## Run

```bash
# Set env vars locally (NEVER commit, NEVER paste in chat)
read -sp "Password for ereport: " APEX_TEST_PASSWORD ; export APEX_TEST_PASSWORD ; echo
export APEX_TEST_DSN="ebstest.vicemhatien.vn:1522/TEST1"
export APEX_TEST_USER="ereport"
export APEX_TEST_WORKSPACE_ID="<numeric>"
export APEX_TEST_SCHEMA="EREPORT"
export APEX_TEST_RUNTIME_URL="<your apex runtime url>"

cd /d/repos/apex-builder-mcp
./.venv/Scripts/python.exe scripts/round_trip_proof.py --report docs/PHASE_0_REPORT.md
```

## Possible failure modes

- Export captures less metadata than internal create wrote → reimport has different counts
- Internal API skipped a side-effect that App Builder UI does (template registration, theme binding) → page imports but runtime errors
- ORA-XXX during reimport (parser strict on internal export format)
- ereport user lacks grants on `apex_export` or `wwv_flow_application_install` (need APEX-internal grants)

## After running

- **PASS** → tag commit `phase-0-passed` → write Plan 2A
- **FAIL** → tag commit `phase-0-failed` → write Plan 2B
