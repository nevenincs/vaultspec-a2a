"""Dispatch guard wording and capacity tokens shared by the executor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..providers import ProviderCondition
from ..thread.enums import ControlActionType
from ..thread.failure_evidence import (
    GraphFailureEvidence,
    failure_detail_fingerprint,
)

if TYPE_CHECKING:
    from ..ipc.schemas import DispatchRequest

__all__ = [
    "_CAPACITY_ACCEPTED",
    "_CAPACITY_FULL",
    "_CAPACITY_THREAD_ACTIVE",
    "_EXECUTOR_CONDITION",
    "_INGEST_GUARDS",
    "_RESUME_GUARDS",
    "_SLOT_OWNING_ACTIONS",
    "DispatchCapacityReservation",
    "_GuardWording",
    "failure_evidence",
]


@dataclass(frozen=True, slots=True)
class _GuardWording:
    """Per-runtime-mode wording for the arms ingest and resume share.

    The pre-run guards (compile failure, missing graph, ingest slot already held)
    and the execution catch-all are one behaviour each, reached from two dispatch
    modes. Only the operator-facing wording and the log actions differ between
    the modes, so they are data here and each arm has a single implementation.

    The ``*_detail`` fields are the client's wording, the rest the operator's.
    The operator's carry the run identifier; the client's deliberately do not -
    the run they describe is the one the reader is already looking at, and
    repeating the identifier spends a capped reason on what the frame carries.
    """

    runtime_mode: str
    compile_failure: str
    graph_missing: str
    graph_missing_detail: str
    slot_held: str
    slot_held_action: str
    execution_failure: str
    execution_failure_action: str
    execution_failure_detail: str


_INGEST_GUARDS = _GuardWording(
    runtime_mode="ingest",
    compile_failure="Graph compilation failed for thread %s: %s",
    graph_missing="No graph for thread %s -- no team preset provided",
    graph_missing_detail="No graph to run: the dispatch named no team preset",
    slot_held="Ingest already active for thread %s -- dropping",
    slot_held_action="ingest_rejected_active",
    execution_failure="Ingest failed for thread %s",
    execution_failure_action="ingest_failed",
    execution_failure_detail="Graph execution failed unexpectedly",
)

_RESUME_GUARDS = _GuardWording(
    runtime_mode="resume",
    compile_failure="Graph recompile failed for thread %s: %s",
    graph_missing="No graph for thread %s -- cannot resume",
    graph_missing_detail="No graph to resume: the run has no compiled graph",
    slot_held="Ingest already active for thread %s -- cannot resume",
    slot_held_action="resume_rejected_active",
    execution_failure="Resume failed for thread %s",
    execution_failure_action="resume_failed",
    execution_failure_detail="Graph resume failed unexpectedly",
)

# The provider condition every executor-side rejection resolves to, and it is a
# decision rather than an omission: a graph that refused to compile, a dispatch
# that named no preset, and a fault in the executor's own machinery all failed
# BEFORE any provider was engaged, so there is no provider condition to report
# and claiming one would send the reader after a remedy the run never needed.
# The floor is what keeps such a run from carrying no condition at all.
_EXECUTOR_CONDITION = ProviderCondition.UNKNOWN

# The two dispatch actions that take the thread's ingest slot. A failure in
# either is that dispatch's own to settle; a cancel or an unrecognised action
# never held the slot, so a held slot there belongs to a concurrent run.
_SLOT_OWNING_ACTIONS = frozenset({ControlActionType.INGEST, ControlActionType.RESUME})
_CAPACITY_ACCEPTED = "accepted"
_CAPACITY_THREAD_ACTIVE = "thread_active"
_CAPACITY_FULL = "capacity_full"


@dataclass(frozen=True, slots=True)
class DispatchCapacityReservation:
    """Opaque ownership proof for one admitted ingest or resume dispatch."""

    thread_id: str
    generation: int


def failure_evidence(
    req: DispatchRequest,
    *,
    detail: str | None,
    condition: ProviderCondition,
) -> GraphFailureEvidence | None:
    """Bind one classified worker failure to its accepted graph action."""
    receipt = req.graph_action_receipt
    if receipt is None or not detail:
        return None
    return GraphFailureEvidence(
        schema_version="graph-failure-v1",
        action=receipt,
        outcome="failed",
        detail_fingerprint=failure_detail_fingerprint(detail),
        provider_condition=condition.value,
    )
