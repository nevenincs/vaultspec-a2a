"""Wire-protocol enums for the frontend-backend contract.

API-only enums (``PlanEntryStatus``,
``PlanEntryPriority``) remain local — they are wire-protocol concerns, not
domain concepts.

Domain enums (``ToolKind``, ``PermissionType``, ``PermissionOptionKind``,
``ToolCallStatus``, ``AgentLifecycleState``) are defined in
``vaultspec_a2a.graph.enums``; import them from there directly.

Note: ``Provider`` and ``Model`` live in ``vaultspec_a2a.utils.enums`` and are
imported (not duplicated) where needed.
"""

from enum import StrEnum

__all__ = [
    "PlanEntryPriority",
    "PlanEntryStatus",
]


class PlanEntryStatus(StrEnum):
    """Execution status of a plan entry."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PlanEntryPriority(StrEnum):
    """Priority level for a plan entry."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
