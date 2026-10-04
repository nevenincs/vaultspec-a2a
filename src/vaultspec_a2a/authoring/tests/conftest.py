"""Markers for authoring-package tests.

The unit-level tests here exercise pure decoders and header/URL assembly with
no I/O, so they earn both ``middleware`` (package default) and ``unit``. The
live engine integration tests declare their own ``service`` marker.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest

from ...desktop._platform_acl import harden_credential_path
from ...testing import forfeits_purity

if TYPE_CHECKING:
    from collections.abc import Iterator

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
_LIVE_FILES = frozenset({"test_live_engine.py"})


@pytest.fixture
def secure_engine_dir() -> Iterator[Path]:
    """Isolate trusted producer state outside the repository under a private ACL."""
    # storage-anchor-ok: trusted producer fixtures must be outside any repository.
    with TemporaryDirectory(  # storage-anchor-ok
        prefix="vaultspec-engine-security-"
    ) as directory:
        path = Path(directory)
        harden_credential_path(path)
        yield path


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure-logic tests unit; leave live-engine files to their own marks."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _LIVE_FILES:
            continue
        item.add_marker(pytest.mark.middleware)
        if not forfeits_purity(item):
            item.add_marker(pytest.mark.unit)
