"""Core test configuration — auto-applies the ``core`` + ``unit`` markers.

``test_logging.py`` imports ``control.config.Settings`` (Layer 2), so it
gets ``middleware`` instead of ``core``.
"""

import pytest

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests collected from THIS directory with appropriate layer marker."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name == "test_logging.py":
            item.add_marker(pytest.mark.middleware)
        else:
            item.add_marker(pytest.mark.core)
            item.add_marker(pytest.mark.unit)
