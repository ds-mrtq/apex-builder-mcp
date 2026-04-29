"""Pre-write snapshot + post-write verify + post-fail freeze (spec section 4.3).

Detect side-effects that didn't roll back cleanly. If post-fail metadata
differs from pre-write snapshot, the rollback was incomplete (likely an
internal autonomous transaction or DDL inside an APEX proc) and the
profile should freeze until human review.
"""
from __future__ import annotations

from dataclasses import dataclass


class PostFailFreezeError(RuntimeError):
    """Raised when post-fail metadata differs from pre-write — freeze profile."""


@dataclass(frozen=True)
class MetadataSnapshot:
    pages: int
    regions: int
    items: int


def verify_post_success(
    before: MetadataSnapshot,
    after: MetadataSnapshot,
    expected_delta: dict[str, int],
) -> tuple[bool, str]:
    """After successful write, verify metadata changed by expected delta.

    Only fields in expected_delta are checked. Other fields may differ.
    """
    actual = {
        "pages": after.pages - before.pages,
        "regions": after.regions - before.regions,
        "items": after.items - before.items,
    }
    for k, expected in expected_delta.items():
        if actual.get(k, 0) != expected:
            return (
                False,
                f"expected delta {k}={expected}, got {actual.get(k, 0)} "
                f"(before={before}, after={after})",
            )
    return (True, "delta matches expectation")


def verify_post_fail(
    before: MetadataSnapshot,
    after: MetadataSnapshot,
) -> None:
    """After write FAILED, verify metadata fully reverted (no side effect leak)."""
    if before == after:
        return
    raise PostFailFreezeError(
        f"post-fail metadata drift detected: before={before}, after={after}. "
        "Rollback did not fully revert side effects. Profile should freeze "
        "until human review."
    )
