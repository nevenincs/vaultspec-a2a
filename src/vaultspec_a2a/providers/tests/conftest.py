"""Middleware test configuration for providers/tests/."""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)

# Files that spawn a real ACP subprocess / network I/O declare their own
# ``service`` marker and must NOT receive the pure ``unit``/``middleware`` marks.
_LIVE_FILES = frozenset(
    {
        "test_acp_authoring_bridge.py",
        "test_authoring_stdio_bridge.py",
        "test_acp_migration_surface.py",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure provider tests as ``middleware`` + ``unit``.

    These tests exercise pure provider logic — command classification, auth-env
    construction, exception mapping, path-security validation — with no real
    subprocess spawn or network I/O, so they carry the orthogonal ``unit`` marker.
    Live subprocess files are left to their own ``service`` marker.
    """
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _LIVE_FILES:
            continue
        item.add_marker(pytest.mark.middleware)
        item.add_marker(pytest.mark.unit)
