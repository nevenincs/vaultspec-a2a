"""Fixtures and hooks for database-layer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


# Most database tests drive a real SQLite engine and are impure; these test pure
# logic only (path validation) and also earn the orthogonal ``unit`` marker.
_PURE_FILES = frozenset({"test_artifact_repository.py"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark all database tests as ``middleware`` (+``unit`` for pure files)."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        item.add_marker(pytest.mark.middleware)
        if item.path.name in _PURE_FILES:
            item.add_marker(pytest.mark.unit)


@pytest.fixture
def runtime_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a local writable runtime dir instead of pytest's global temp root.

    The workspace can be mounted on a filesystem that does not behave reliably
    for file-backed SQLite WAL/migration tests. Use the local Codex writable
    root so these tests exercise SQLite itself rather than mapped-drive quirks.
    """
    return tmp_path_factory.mktemp("database-tests")
