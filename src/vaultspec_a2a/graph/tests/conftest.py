"""Fixtures for graph-layer tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...providers import ProviderFactory

if TYPE_CHECKING:
    from ..protocols import ProviderFactoryProtocol


@pytest.fixture
def pf() -> ProviderFactoryProtocol:
    """The real provider factory, which serves the deterministic lane in tests."""
    return ProviderFactory()
