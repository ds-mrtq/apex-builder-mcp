# tests/unit/test_id_allocator.py
from __future__ import annotations

from apex_builder_mcp.apex_api.id_allocator import pick_free_id


def test_pick_first_free_above_zero():
    assert pick_free_id(used=set(), min_id=1) == 1


def test_skip_existing_max_plus_1():
    assert pick_free_id(used={1, 2, 3}, min_id=1) == 4


def test_fill_gap():
    assert pick_free_id(used={1, 2, 4, 5}, min_id=1) == 3


def test_min_id_respected():
    assert pick_free_id(used={1, 2, 3}, min_id=10) == 10


def test_min_id_inside_used():
    assert pick_free_id(used={10, 11, 12}, min_id=10) == 13
