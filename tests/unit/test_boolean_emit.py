# tests/unit/test_boolean_emit.py
from __future__ import annotations

import pytest

from apex_builder_mcp.apex_api.boolean_emit import (
    BooleanEmitError,
    emit_bool,
    is_bool_param_name,
)


def test_emit_true():
    assert emit_bool(True) == "true"


def test_emit_false():
    assert emit_bool(False) == "false"


def test_string_true_rejected():
    with pytest.raises(BooleanEmitError):
        emit_bool("true")  # type: ignore


def test_int_one_rejected():
    with pytest.raises(BooleanEmitError):
        emit_bool(1)  # type: ignore


def test_none_rejected():
    with pytest.raises(BooleanEmitError):
        emit_bool(None)  # type: ignore


def test_known_bool_param_names():
    assert is_bool_param_name("p_use_as_row_header") is True
    assert is_bool_param_name("p_filter_exact_match") is True
    assert is_bool_param_name("p_required_yn") is False  # YN is char(1), not bool
    assert is_bool_param_name("p_id") is False
