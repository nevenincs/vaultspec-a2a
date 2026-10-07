"""Fixtures for database-layer tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runtime_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a local writable runtime dir instead of pytest's global temp root.

    The workspace can be mounted on a filesystem that does not behave reliably
    for file-backed SQLite WAL/migration tests. Use the local Codex writable
    root so these tests exercise SQLite itself rather than mapped-drive quirks.
    """
    return tmp_path_factory.mktemp("database-tests")
