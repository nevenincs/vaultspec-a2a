"""Middleware test configuration — auto-applies the ``middleware`` marker."""

import pytest

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests here as ``middleware`` + ``unit`` (pure schema validation, no I/O)."""
    for item in items:
        if str(item.path).startswith(_PACKAGE_DIR):
            item.add_marker(pytest.mark.middleware)
            item.add_marker(pytest.mark.unit)
