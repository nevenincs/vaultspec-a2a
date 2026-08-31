"""Core test configuration — auto-applies the ``core`` + ``unit`` markers.

``test_logging.py`` imports ``control.config.Settings`` (Layer 2), so it
gets ``middleware`` instead of ``core``.
"""

import pytest

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)

# Core-layer tests that really do spawn a child process. They keep ``core`` but
# are not pure, so the orthogonal ``unit`` claim is withheld - a wrong marker is
# worse than none, because a selection excluding impure tests silently includes
# anything missing from this set.
_IMPURE_FILES = frozenset(
    {
        "test_logging_entrypoints.py",
        "test_process_containment.py",
        "test_runtime_exec.py",
    }
)


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
        elif item.path.name == "test_process.py":
            # Real subprocess I/O — middleware on the layer axis, not a unit test.
            item.add_marker(pytest.mark.middleware)
        else:
            item.add_marker(pytest.mark.core)
            if item.path.name not in _IMPURE_FILES:
                item.add_marker(pytest.mark.unit)
