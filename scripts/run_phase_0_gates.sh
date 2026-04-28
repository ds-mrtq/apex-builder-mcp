#!/bin/bash
# Phase 0 Gates 2 + 5 runner — uses SQLcl saved connection (no password).
#
# Same UX as SQLcl MCP: SQLcl resolves password from its own encrypted store.
# We never see the password. Run from Git Bash on Windows.
#
# Usage:
#   cd /d/repos/apex-builder-mcp
#   ./scripts/run_phase_0_gates.sh

set -u

cd "$(dirname "$0")/.." || { echo "Cannot cd into repo root"; exit 2; }
export MSYS2_ARG_CONV_EXCL='*'

# Static config — SQLcl saved connection name, workspace, schema, runtime URL
export APEX_TEST_SQLCL_NAME="ereport_test8001"
export APEX_TEST_WORKSPACE="EREPORT"
export APEX_TEST_SCHEMA="EREPORT"
export APEX_TEST_RUNTIME_URL="https://apexdev.vicemhatien.com.vn/ords/r/ereport"

# ----------------------------------------------------------------------------
# Pre-flight: verify SQLcl can connect using saved password
# ----------------------------------------------------------------------------
echo "[1/3] Verifying SQLcl connection $APEX_TEST_SQLCL_NAME..."
PRECHECK=$(printf "set heading off feedback off pagesize 0\nselect 'OK_CHK' from dual;\nexit\n" \
    | sql -name "$APEX_TEST_SQLCL_NAME" 2>&1)
if ! echo "$PRECHECK" | grep -q "OK_CHK"; then
  echo "ERROR: cannot connect via 'sql -name $APEX_TEST_SQLCL_NAME'. Output:"
  echo "$PRECHECK"
  exit 1
fi
echo "    OK"

# ----------------------------------------------------------------------------
# Gate 2: 5 sample WWV_FLOW_IMP_PAGE calls (PL/SQL via SQLcl)
# ----------------------------------------------------------------------------
echo
echo "============================================================"
echo "[2/3] Gate 2: 5 sample WWV_FLOW_IMP_PAGE calls"
echo "============================================================"

# Lookup workspace_id
WS_ID=$(printf "set heading off feedback off pagesize 0\nselect workspace_id from apex_workspaces where upper(workspace) = '%s';\nexit\n" \
    "$APEX_TEST_WORKSPACE" | sql -name "$APEX_TEST_SQLCL_NAME" 2>&1 \
    | grep -E '^[ ]*[0-9]+[ ]*$' | head -1 | tr -d ' ')
if [[ -z "$WS_ID" ]]; then
  echo "ERROR: could not lookup workspace_id for $APEX_TEST_WORKSPACE"
  exit 1
fi
echo "    Workspace $APEX_TEST_WORKSPACE → ID $WS_ID"

SBOX_ID=$((900000 + RANDOM % 99999))
echo "    Sandbox app id: $SBOX_ID"

GATE2_OUT=$(sql -name "$APEX_TEST_SQLCL_NAME" 2>&1 <<EOF
set echo on feedback on
begin
  wwv_flow_application_install.set_workspace_id($WS_ID);
  wwv_flow_application_install.set_schema('$APEX_TEST_SCHEMA');
  wwv_flow_application_install.set_application_id($SBOX_ID);
  wwv_flow_application_install.generate_offset;
  wwv_flow_imp.create_application(
    p_id => $SBOX_ID,
    p_owner => '$APEX_TEST_SCHEMA',
    p_name => '_TEST_APEXBLD_' || $SBOX_ID,
    p_alias => '_TST_' || $SBOX_ID,
    p_application_group => 0
  );
  wwv_flow_imp_page.create_page(
    p_id => 1, p_name => 'Sandbox', p_step_title => 'Sandbox'
  );
  wwv_flow_imp_page.create_page_plug(
    p_id => 100, p_plug_name => 'TestRegion',
    p_plug_template => 0, p_plug_display_sequence => 10,
    p_plug_source_type => 'NATIVE_HTML',
    p_plug_query_options => 'DERIVED_REPORT_COLUMNS'
  );
  wwv_flow_imp_page.create_page_item(
    p_id => 200, p_name => 'P1_TEST',
    p_item_sequence => 10, p_item_plug_id => 100,
    p_display_as => 'NATIVE_TEXT_FIELD'
  );
  wwv_flow_imp_page.create_page_button(
    p_id => 300, p_button_sequence => 10, p_button_plug_id => 100,
    p_button_name => 'BTN_OK', p_button_action => 'SUBMIT',
    p_button_template_id => 0, p_button_image_alt => 'OK'
  );
  wwv_flow_imp_page.create_page_process(
    p_id => 400, p_process_sequence => 10, p_process_type => 'NATIVE_PLSQL',
    p_process_name => 'PROC_TEST', p_process_sql_clob => 'null;'
  );
  commit;
end;
/
prompt --- region count check ---
select count(*) as region_count
  from apex_application_page_regions where application_id = $SBOX_ID;
prompt --- cleanup ---
begin
  begin wwv_flow_imp.remove_flow($SBOX_ID); exception when others then null; end;
  commit;
end;
/
exit
EOF
)

echo "$GATE2_OUT"

# Gate 2 passes iff: no ORA-, no PLS-, region_count >= 1
if echo "$GATE2_OUT" | grep -qE "(ORA-[0-9]+|PLS-[0-9]+)"; then
  echo
  echo "Gate 2: FAIL — ORA/PLS error detected in output"
  GATE2_RC=1
elif echo "$GATE2_OUT" | grep -qE "region_count[^0-9]+[1-9]" ; then
  echo
  echo "Gate 2: PASS — 5 calls succeeded, region_count >= 1"
  GATE2_RC=0
else
  echo
  echo "Gate 2: FAIL — could not confirm region_count from output"
  GATE2_RC=1
fi

# ----------------------------------------------------------------------------
# Gate 5: Round-Trip Proof (Python harness, also via SQLcl)
# ----------------------------------------------------------------------------
echo
echo "============================================================"
echo "[3/3] Gate 5: Round-Trip Proof (the deciding gate)"
echo "============================================================"
./.venv/Scripts/python.exe scripts/round_trip_proof.py --report docs/PHASE_0_REPORT.md
GATE5_RC=$?

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
echo
echo "============================================================"
echo "Phase 0 Gates Summary"
echo "============================================================"
[[ $GATE2_RC -eq 0 ]] && echo "Gate 2: PASS" || echo "Gate 2: FAIL (rc=$GATE2_RC)"
[[ $GATE5_RC -eq 0 ]] && echo "Gate 5: PASS" || echo "Gate 5: FAIL (rc=$GATE5_RC)"
echo
echo "Per spec auto-pivot rule:"
if [[ $GATE2_RC -eq 0 && $GATE5_RC -eq 0 ]]; then
  echo "  Both PASS → proceed to Plan 2A: Direct-Write MVP"
  exit 0
else
  echo "  Any FAIL → proceed to Plan 2B: File-Based Pivot MVP"
  exit 1
fi
