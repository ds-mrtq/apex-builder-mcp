# tests/unit/test_lazy_loader.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.registry.categories import Category
from apex_builder_mcp.registry.lazy_loader import LazyToolLoader, NotLoadableError


def test_starts_with_always_loaded():
    loader = LazyToolLoader()
    loader.bootstrap()  # registers always-loaded categories
    loaded = loader.loaded_categories()
    assert Category.CORE in loaded
    assert Category.LAZY_META in loaded
    assert Category.READ_DB not in loaded  # not always-loaded


def test_load_category_adds_it():
    loader = LazyToolLoader()
    loader.bootstrap()
    notify_mock = MagicMock()
    loader.set_notify_callback(notify_mock)

    loader.load(Category.WRITE_CORE)

    assert Category.WRITE_CORE in loader.loaded_categories()
    notify_mock.assert_called_once()


def test_unload_removes_unless_always_loaded():
    loader = LazyToolLoader()
    loader.bootstrap()
    loader.load(Category.WRITE_CORE)
    notify_mock = MagicMock()
    loader.set_notify_callback(notify_mock)

    loader.unload(Category.WRITE_CORE)
    assert Category.WRITE_CORE not in loader.loaded_categories()
    notify_mock.assert_called_once()


def test_unload_always_loaded_raises():
    loader = LazyToolLoader()
    loader.bootstrap()
    with pytest.raises(NotLoadableError):
        loader.unload(Category.CORE)


def test_post_connect_auto_loads_read_categories():
    loader = LazyToolLoader()
    loader.bootstrap()
    loader.set_notify_callback(MagicMock())
    loader.on_post_connect()
    assert Category.READ_DB in loader.loaded_categories()
    assert Category.READ_APEX in loader.loaded_categories()
