# tests/unit/test_all_arguments.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.apex_api.all_arguments import (
    SignatureCache,
    SignatureMismatchError,
    verify_call_against_signature,
)


def test_signature_cache_records_args():
    cache = SignatureCache()
    cache.set(
        "WWV_FLOW_IMP_PAGE.CREATE_PAGE",
        ["P_ID", "P_NAME", "P_USE_AS_ROW_HEADER"],
    )
    sig = cache.get("WWV_FLOW_IMP_PAGE.CREATE_PAGE")
    assert sig == ["P_ID", "P_NAME", "P_USE_AS_ROW_HEADER"]


def test_signature_cache_miss():
    cache = SignatureCache()
    assert cache.get("UNKNOWN") is None


def test_verify_call_ok():
    sig = ["P_ID", "P_NAME"]
    # case-insensitive comparison
    verify_call_against_signature("X.Y", sig, ["p_id", "p_name"])


def test_verify_call_unknown_param_raises():
    sig = ["P_ID", "P_NAME"]
    with pytest.raises(SignatureMismatchError) as exc_info:
        verify_call_against_signature("X.Y", sig, ["p_id", "p_typo"])
    assert "p_typo" in str(exc_info.value).lower()


def test_verify_call_lookup_with_db_uses_cache(monkeypatch):
    cache = SignatureCache()
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_cur.fetchall.return_value = [("P_ID",), ("P_NAME",)]
    fake_cur.__iter__ = lambda self: iter([("P_ID",), ("P_NAME",)])

    sig1 = cache.lookup("WWV.X", connection=fake_conn)
    sig2 = cache.lookup("WWV.X", connection=fake_conn)  # cache hit
    assert sig1 == sig2
    assert fake_conn.cursor.call_count == 1  # only first call hit DB
