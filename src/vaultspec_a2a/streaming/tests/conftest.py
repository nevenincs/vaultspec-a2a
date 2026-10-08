"""Test configuration for streaming-tier tests."""

from __future__ import annotations

import pytest

from ..subscribers import RelayHub


@pytest.fixture
def aggregator() -> RelayHub:
    """Return a fresh RelayHub for each test.

    Shared by the connection-cap and subscription-cap siblings, which drive
    the real relay hub at its real shipped defaults rather than a tuned-down
    one.
    """
    return RelayHub()
