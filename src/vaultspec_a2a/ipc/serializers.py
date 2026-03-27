"""IPC serialization helpers shared between gateway and worker (D-01)."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..streaming.aggregator import SequencedEvent

__all__ = ["sequenced_to_dict"]


def sequenced_to_dict(sequenced: SequencedEvent) -> dict:
    """Serialise a ``SequencedEvent`` to a plain dict (for bridge relay)."""
    d = asdict(sequenced.event)
    d["sequence"] = sequenced.sequence
    return d
