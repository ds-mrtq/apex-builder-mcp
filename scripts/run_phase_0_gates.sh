#!/bin/bash
# Phase 0 Gate 5 round-trip proof runner.
#
# Strategy: clone existing app (default 100 'Data Loading') in EREPORT
# workspace into a sandbox app id, add page/region/item via internal
# wwv_flow_imp_page.* procs (the 3 MVP write paths), verify export
# captures the additions, verify runtime renders, drop clone.
#
# Source app NEVER modified. Uses SQLcl saved connection (no password).
#
# Usage:
#   cd /d/repos/apex-builder-mcp
#   ./scripts/run_phase_0_gates.sh

set -u

cd "$(dirname "$0")/.." || { echo "Cannot cd into repo root"; exit 2; }
export MSYS2_ARG_CONV_EXCL='*'
export PYTHONIOENCODING=utf-8

# Static config — SQLcl saved connection, workspace, schema, runtime URL
export APEX_TEST_SQLCL_NAME="ereport_test8001"
export APEX_TEST_WORKSPACE="EREPORT"
export APEX_TEST_SCHEMA="EREPORT"
export APEX_TEST_RUNTIME_URL="https://apexdev.vicemhatien.com.vn/ords/r/ereport"
export APEX_TEST_SOURCE_APP_ID="${APEX_TEST_SOURCE_APP_ID:-100}"

# ----------------------------------------------------------------------------
# Pre-flight: SQLcl saved connection works
# ----------------------------------------------------------------------------
echo "[1/2] Verifying SQLcl connection $APEX_TEST_SQLCL_NAME..."
PRECHECK=$(printf "set heading off feedback off pagesize 0\nselect 'OK_CHK' from dual;\nexit\n" \
    | sql -name "$APEX_TEST_SQLCL_NAME" 2>&1)
if ! echo "$PRECHECK" | grep -q "OK_CHK"; then
  echo "ERROR: cannot connect via 'sql -name $APEX_TEST_SQLCL_NAME'"
  echo "$PRECHECK"
  exit 1
fi
echo "    OK"

# ----------------------------------------------------------------------------
# Gate 5 round-trip proof (also covers Gate 2 verification of the 3 internal
# wwv_flow_imp_page.* procs we actually need for MVP)
# ----------------------------------------------------------------------------
echo
echo "============================================================"
echo "[2/2] Gate 5: Round-Trip Proof (clone strategy)"
echo "  source app: $APEX_TEST_SOURCE_APP_ID"
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
if [[ $GATE5_RC -eq 0 ]]; then
  echo "Gate 5: PASS"
  echo
  echo "Per spec auto-pivot rule:"
  echo "  Gate 5 PASS -> proceed to Plan 2A: Direct-Write MVP"
  echo
  echo "Note: Gate 2 (5 sample WWV calls) was superseded — round-trip proof"
  echo "covers the 3 MVP procs (create_page, create_page_plug, create_page_item)"
  echo "in step 5 of Gate 5. wwv_flow_imp.create_application/create_flow are"
  echo "out of MVP scope (no app-creation tools planned)."
  exit 0
else
  echo "Gate 5: FAIL (rc=$GATE5_RC)"
  echo
  echo "Per spec auto-pivot rule:"
  echo "  Gate 5 FAIL -> proceed to Plan 2B: File-Based Pivot MVP"
  echo "See docs/PHASE_0_REPORT.md for findings JSON."
  exit 1
fi
