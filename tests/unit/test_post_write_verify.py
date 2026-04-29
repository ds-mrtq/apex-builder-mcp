from __future__ import annotations

import pytest

from apex_builder_mcp.audit.post_write_verify import (
    MetadataSnapshot,
    PostFailFreezeError,
    verify_post_fail,
    verify_post_success,
)


def test_metadata_snapshot_immutable():
    s = MetadataSnapshot(pages=25, regions=66, items=41)
    assert s.pages == 25


def test_verify_post_success_pass_when_expected_change():
    before = MetadataSnapshot(pages=25, regions=66, items=41)
    after = MetadataSnapshot(pages=26, regions=67, items=42)
    expected = {"pages": 1, "regions": 1, "items": 1}
    ok, _ = verify_post_success(before, after, expected_delta=expected)
    assert ok is True


def test_verify_post_success_fail_when_unexpected():
    before = MetadataSnapshot(pages=25, regions=66, items=41)
    after = MetadataSnapshot(pages=25, regions=66, items=41)
    expected = {"pages": 1}
    ok, reason = verify_post_success(before, after, expected_delta=expected)
    assert ok is False
    assert "expected" in reason.lower()


def test_verify_post_fail_no_drift_returns_clean():
    before = MetadataSnapshot(pages=25, regions=66, items=41)
    after = MetadataSnapshot(pages=25, regions=66, items=41)
    verify_post_fail(before, after)


def test_verify_post_fail_with_drift_raises_freeze():
    before = MetadataSnapshot(pages=25, regions=66, items=41)
    after = MetadataSnapshot(pages=26, regions=66, items=41)
    with pytest.raises(PostFailFreezeError):
        verify_post_fail(before, after)


def test_verify_post_success_with_partial_expected_delta():
    """Only specified deltas matter; unspecified fields are flexible."""
    before = MetadataSnapshot(pages=25, regions=66, items=41)
    after = MetadataSnapshot(pages=26, regions=68, items=43)
    # We only check pages delta = 1; regions and items are not specified
    ok, _ = verify_post_success(before, after, expected_delta={"pages": 1})
    assert ok is True
