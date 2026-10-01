"""A probe that passes at once, for proofs about how the owner starts pytest."""

from __future__ import annotations


def test_passes_at_once() -> None:
    """Nothing to wait for: what is proven is how the session was started."""
