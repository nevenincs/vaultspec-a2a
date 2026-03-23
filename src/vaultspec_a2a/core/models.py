"""Compatibility shim — re-exports from vaultspec_a2a.thread.models.

This module exists solely so that ``from ..core.models import X``
continues to work during the core-layer decomposition.  It will be
removed in Phase 7 when all consumers are updated to import from
``vaultspec_a2a.thread.models`` directly.
"""

from vaultspec_a2a.thread.models import (
    ArtifactRef as ArtifactRef,
)
from vaultspec_a2a.thread.models import (
    PlanStep as PlanStep,
)
from vaultspec_a2a.thread.models import (
    TokenUsageEntry as TokenUsageEntry,
)

__all__ = [
    "ArtifactRef",
    "PlanStep",
    "TokenUsageEntry",
]
