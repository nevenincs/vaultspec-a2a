"""Middleware test configuration for providers/tests/."""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark all provider tests as ``middleware`` + ``unit``.

    These tests exercise pure provider logic — command classification, auth-env
    construction, exception mapping, path-security validation — with no real
    subprocess spawn or network I/O, so they carry the orthogonal ``unit`` marker.
    """
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        item.add_marker(pytest.mark.middleware)
        item.add_marker(pytest.mark.unit)
