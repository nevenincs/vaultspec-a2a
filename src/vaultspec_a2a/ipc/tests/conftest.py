"""Core test configuration — auto-applies the ``core`` + ``unit`` markers.

The IPC serializer tests exercise pure data-transformation helpers
(``ipc/serializers.py``) with no I/O, so they are Layer 1 ``core`` and, being
pure, also carry the orthogonal ``unit`` purity marker.
"""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests collected from THIS directory as ``core`` + ``unit``."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        item.add_marker(pytest.mark.core)
        item.add_marker(pytest.mark.unit)
