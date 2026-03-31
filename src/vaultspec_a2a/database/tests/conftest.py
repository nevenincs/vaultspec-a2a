"""Fixtures and hooks for database-layer tests."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark all database tests as ``middleware``."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        item.add_marker(pytest.mark.middleware)


@pytest.fixture
def runtime_dir() -> Path:
    """Return a local writable runtime dir instead of pytest's global temp root.

    The workspace can be mounted on a filesystem that does not behave reliably
    for file-backed SQLite WAL/migration tests. Use the local Codex writable
    root so these tests exercise SQLite itself rather than mapped-drive quirks.
    """
    root = Path.home() / ".codex" / "memories" / "tmp" / "database-tests" / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root
