"""Layer 2 test configuration — auto-applies ``layer2`` marker to pure tests.

Tests marked ``live``, ``requires_vidaimock``, or other infra markers are
excluded so they remain gated by their infrastructure requirements.
"""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
_INFRA_MARKERS = frozenset(
    {
        "live",
        "requires_postgres",
        "requires_jaeger",
        "requires_vidaimock",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure provider tests as ``layer2``, excluding infra-marked tests."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if any(item.get_closest_marker(m) for m in _INFRA_MARKERS):
            continue
        item.add_marker(pytest.mark.layer2)
