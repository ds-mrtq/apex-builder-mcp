#!/bin/bash
# Phase 0 Gates 2 + 5 runner — apex-builder-mcp
#
# Run from Git Bash on Windows. Prompts for DB password (silent), looks up
# the APEX workspace_id, then runs Gate 2 (5 sample WWV calls) and Gate 5
# (round-trip proof — the deciding gate).
#
# Usage:
#   cd /d/repos/apex-builder-mcp
#   ./scripts/run_phase_0_gates.sh
#
# Gate 2 + 5 results land in docs/PHASE_0_REPORT.md (Gate 5 appends JSON
# findings). Manual interpretation needed afterwards.

set -u

cd "$(dirname "$0")/.." || { echo "Cannot cd into repo root"; exit 2; }

# ----------------------------------------------------------------------------
# Prompt password (silent — never logged, never persisted)
# ----------------------------------------------------------------------------
read -srp "Password for ereport@TEST1: " APEX_TEST_PASSWORD
echo
if [[ -z "$APEX_TEST_PASSWORD" ]]; then
  echo "ERROR: empty password"
  exit 1
fi
export APEX_TEST_PASSWORD

# ----------------------------------------------------------------------------
# Static env vars — TEST env, EREPORT schema/workspace
# (no secrets here; safe to commit)
# ----------------------------------------------------------------------------
export APEX_TEST_DSN="ebstest.vicemhatien.vn:1522/TEST1"
export APEX_TEST_USER="ereport"
export APEX_TEST_SCHEMA="EREPORT"
export APEX_TEST_SQLCL_NAME="ereport_test8001"
# APEX runtime URL — workspace 'EREPORT' lowercased to ORDS path:
export APEX_TEST_RUNTIME_URL="https://apexdev.vicemhatien.com.vn/ords/r/ereport"

# ----------------------------------------------------------------------------
# Lookup workspace_id from DB
# ----------------------------------------------------------------------------
echo
echo "[1/3] Looking up APEX workspace_id for 'EREPORT'..."
WORKSPACE_ID=$(./.venv/Scripts/python.exe -c "
import os, sys, oracledb
try:
    conn = oracledb.connect(
        user=os.environ['APEX_TEST_USER'],
        password=os.environ['APEX_TEST_PASSWORD'],
        dsn=os.environ['APEX_TEST_DSN'],
    )
    cur = conn.cursor()
    cur.execute(
        \"select workspace_id from apex_workspaces where upper(workspace) = 'EREPORT'\"
    )
    row = cur.fetchone()
    if row is None:
        sys.stderr.write('Workspace EREPORT not found in apex_workspaces\n')
        sys.exit(2)
    print(int(row[0]))
    conn.close()
except oracledb.DatabaseError as e:
    sys.stderr.write(f'DB error: {e}\n')
    sys.exit(3)
" 2>&1)

LOOKUP_RC=$?
if [[ $LOOKUP_RC -ne 0 ]]; then
  echo "ERROR: workspace lookup failed (rc=$LOOKUP_RC):"
  echo "$WORKSPACE_ID"
  unset APEX_TEST_PASSWORD
  exit 1
fi
export APEX_TEST_WORKSPACE_ID="$WORKSPACE_ID"
echo "    Workspace ID: $WORKSPACE_ID"

# ----------------------------------------------------------------------------
# Gate 2: 5 sample WWV_FLOW_IMP_PAGE calls
# ----------------------------------------------------------------------------
echo
echo "============================================================"
echo "[2/3] Gate 2: 5 sample WWV_FLOW_IMP_PAGE calls"
echo "============================================================"
./.venv/Scripts/pytest.exe tests/integration/test_wwv_calls_real.py -v --integration -s
GATE2_RC=$?

# ----------------------------------------------------------------------------
# Gate 5: Round-Trip Proof
# ----------------------------------------------------------------------------
echo
echo "============================================================"
echo "[3/3] Gate 5: Round-Trip Proof (the deciding gate)"
echo "============================================================"
./.venv/Scripts/python.exe scripts/round_trip_proof.py --report docs/PHASE_0_REPORT.md
GATE5_RC=$?

# ----------------------------------------------------------------------------
# Clear sensitive env
# ----------------------------------------------------------------------------
unset APEX_TEST_PASSWORD

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
echo
echo "============================================================"
echo "Phase 0 Gates Summary"
echo "============================================================"
if [[ $GATE2_RC -eq 0 ]]; then
  echo "Gate 2: PASS (5 WWV calls succeeded)"
else
  echo "Gate 2: FAIL (rc=$GATE2_RC)"
fi
if [[ $GATE5_RC -eq 0 ]]; then
  echo "Gate 5: PASS (round-trip proof succeeded)"
else
  echo "Gate 5: FAIL (rc=$GATE5_RC) — see docs/PHASE_0_REPORT.md for findings"
fi

echo
echo "Per spec auto-pivot rule:"
if [[ $GATE2_RC -eq 0 && $GATE5_RC -eq 0 ]]; then
  echo "  Both PASS -> proceed to Plan 2A: Direct-Write MVP"
  exit 0
else
  echo "  Any FAIL -> proceed to Plan 2B: File-Based Pivot MVP"
  exit 1
fi
