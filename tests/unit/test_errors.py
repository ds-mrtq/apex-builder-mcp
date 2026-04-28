# tests/unit/test_errors.py
from __future__ import annotations

import pytest

from apex_builder_mcp.schema.errors import ApexBuilderError


def test_error_has_required_fields():
    err = ApexBuilderError(
        code="ENV_GUARD_BLOCKED",
        message="Cannot write to PROD",
        suggestion="Use dry-run or manual App Builder pipeline",
    )
    assert err.code == "ENV_GUARD_BLOCKED"
    assert err.suggestion is not None


def test_error_to_dict_for_mcp():
    err = ApexBuilderError(
        code="PLS_00306",
        message="Boolean param quoted",
        suggestion="Pass real bool",
        sql_attempted="begin x(p_b => 'false'); end;",
        metadata={"tool": "apex_add_page"},
    )
    d = err.to_dict()
    assert d["code"] == "PLS_00306"
    assert d["sql_attempted"] is not None
    assert d["metadata"]["tool"] == "apex_add_page"


def test_error_raise_and_catch():
    with pytest.raises(ApexBuilderError) as exc_info:
        raise ApexBuilderError(code="X", message="Y", suggestion="Z")
    assert exc_info.value.code == "X"
