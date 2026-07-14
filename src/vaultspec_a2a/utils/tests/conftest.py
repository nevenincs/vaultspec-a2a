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
            # Layer 2 by import (control.config.Settings) but pure (no I/O),
            # so it is middleware on the layer axis and still ``unit`` on purity.
            item.add_marker(pytest.mark.middleware)
            item.add_marker(pytest.mark.unit)
        else:
            item.add_marker(pytest.mark.core)
            item.add_marker(pytest.mark.unit)
