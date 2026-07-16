"""Markers for authoring-package tests.

The unit-level tests here exercise pure decoders and header/URL assembly with
no I/O, so they earn both ``middleware`` (package default) and ``unit``. The
live engine integration tests declare their own ``service`` marker.
"""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
_LIVE_FILES = frozenset({"test_live_engine.py"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure-logic tests unit; leave live-engine files to their own marks."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _LIVE_FILES:
            continue
        item.add_marker(pytest.mark.middleware)
        item.add_marker(pytest.mark.unit)
