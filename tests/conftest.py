"""Shared pytest fixtures."""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --integration flag passed."""
    if config.getoption("-m") and "integration" in config.getoption("-m"):
        return
    skip_integration = pytest.mark.skip(reason="run with -m integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def tmp_profiles_yaml(tmp_path):
    """Sample profiles.yaml for tests."""
    yaml_path = tmp_path / "profiles.yaml"
    yaml_path.write_text(
        """
profiles:
  DEV1:
    sqlcl_name: HTC_DEV1
    environment: DEV
    workspace: HTC_OPS
  TEST1:
    sqlcl_name: HTC_TEST1
    environment: TEST
    workspace: HTC_OPS
    require_dry_run: true
  PROD:
    sqlcl_name: HTC_PROD
    environment: PROD
    workspace: HTC_OPS
    require_dry_run: true
    block_destructive: true
""".strip(),
        encoding="utf-8",
    )
    return yaml_path
