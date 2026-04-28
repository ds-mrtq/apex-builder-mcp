"""Shared pytest fixtures."""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add --integration CLI flag."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests (need real DB DEV — slow).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip tests marked `integration` unless --integration was passed."""
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="needs --integration flag")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


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
