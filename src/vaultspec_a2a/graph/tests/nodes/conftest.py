"""Marker overrides for graph/tests/nodes/.

``test_worker_integration.py`` imports from ``providers.acp_chat_model``
(Layer 2) and spawns a subprocess — it must run under ``middleware``,
not ``core``.  All other node tests stay ``core`` + ``unit`` via the
parent conftest.
"""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
_MIDDLEWARE_FILES = frozenset(
    {"test_worker_integration.py", "test_worker_authoring_wiring.py"}
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Override markers for specific node test files."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _MIDDLEWARE_FILES:
            # Remove core/unit markers from parent conftest, apply middleware
            for marker_name in ("core", "unit"):
                marker = item.get_closest_marker(marker_name)
                if marker:
                    item.own_markers = [
                        m for m in item.own_markers if m.name != marker_name
                    ]
            item.add_marker(pytest.mark.middleware)
