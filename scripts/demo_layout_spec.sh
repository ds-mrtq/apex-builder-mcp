#!/bin/bash
# Demo: connect → describe app → load write categories → apply LayoutSpec dry-run
# (Full live demo blocked by oracledb pool gap — see PLAN_2A_REPORT.md)

set -u
cd "$(dirname "$0")/.."
export MSYS2_ARG_CONV_EXCL='*'
export APEX_TEST_SQLCL_NAME="ereport_test8001"
export APEX_TEST_WORKSPACE="EREPORT"

./.venv/Scripts/python.exe <<'EOF'
import json
import os
from apex_builder_mcp.connection.state import get_state, reset_state_for_tests
from apex_builder_mcp.schema.profile import Profile
from apex_builder_mcp.tools.layout_spec import apex_apply_layout_spec

reset_state_for_tests()
state = get_state()
state.set_profile(Profile(
    sqlcl_name=os.environ["APEX_TEST_SQLCL_NAME"],
    environment="TEST",  # dry-run; no live writes
    workspace=os.environ["APEX_TEST_WORKSPACE"],
    auth_mode="sqlcl",
))
state.mark_connected()

spec = {
    "app_id": 100,
    "page_id": 8000,
    "regions": [
        {
            "name": "demo_region",
            "template": "t-Region",
            "grid": {"col_span": 12},
            "items": [
                {"name": "P8000_X", "type": "TEXT"},
                {"name": "P8000_Y", "type": "DATE"},
            ],
        },
    ],
}

result = apex_apply_layout_spec(spec)
print("=== Demo: apply_layout_spec on TEST env (dry-run) ===")
print(json.dumps(result, indent=2, default=str))
EOF
