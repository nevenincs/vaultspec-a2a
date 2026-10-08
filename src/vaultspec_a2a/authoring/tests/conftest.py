"""Fixtures for authoring-package tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ._engine_peer import private_engine_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def secure_engine_dir() -> Iterator[Path]:
    """Isolate trusted producer state outside the repository under a private ACL."""
    with private_engine_dir() as path:
        yield path
