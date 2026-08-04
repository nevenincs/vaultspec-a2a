"""Layer 1 test configuration — auto-applies the ``core`` marker."""

import pytest

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


# Core-layer tests that really do spawn a fresh interpreter. They keep ``core``
# but are not pure, so the orthogonal ``unit`` claim is withheld - a wrong
# marker is worse than none, because a selection excluding impure tests silently
# includes anything missing from this set.
_IMPURE_CORE_FILES = frozenset({"test_import_isolation.py"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests collected from THIS directory as ``core``."""
    for item in items:
        if str(item.path).startswith(_PACKAGE_DIR):
            item.add_marker(pytest.mark.core)
            if item.path.name not in _IMPURE_CORE_FILES:
                item.add_marker(pytest.mark.unit)
