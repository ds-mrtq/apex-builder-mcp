"""Gate 5: Round-Trip Proof — runs the harness script."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def test_round_trip_proof():
    required = [
        "APEX_TEST_DSN", "APEX_TEST_USER", "APEX_TEST_PASSWORD",
        "APEX_TEST_WORKSPACE_ID", "APEX_TEST_SCHEMA", "APEX_TEST_RUNTIME_URL",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        pytest.skip(f"Missing env vars: {missing}")
    result = subprocess.run(
        [sys.executable, "scripts/round_trip_proof.py"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, (
        "Round-trip proof FAILED — see PHASE_0_REPORT.md → trigger Plan 2B (file-based pivot)"
    )
