"""CLI test configuration — auto-applies the ``middleware`` marker."""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests collected from THIS directory as ``middleware``."""
    for item in items:
        if str(item.path).startswith(_PACKAGE_DIR):
            item.add_marker(pytest.mark.middleware)
