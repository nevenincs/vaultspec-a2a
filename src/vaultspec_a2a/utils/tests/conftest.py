"""Core test configuration — auto-applies the ``core`` marker."""

import pytest

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests collected from THIS directory as ``core``."""
    for item in items:
        if str(item.path).startswith(_PACKAGE_DIR):
            item.add_marker(pytest.mark.core)
