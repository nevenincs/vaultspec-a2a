"""Fixtures for authoring-package tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest

from ...desktop._platform_acl import harden_credential_path

if TYPE_CHECKING:
    from collections.abc import Iterator


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
