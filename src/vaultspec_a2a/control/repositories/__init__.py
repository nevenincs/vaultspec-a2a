"""Control-plane persistence boundaries for durable orchestration sagas.

These repositories own the control-owned durable state that coordinates work
spanning more than one store. Unlike the row-level repositories in
:mod:`vaultspec_a2a.database`, they encode control-plane lifecycle rules -
idempotent creation, claiming, advancement, and finalization - over that state.

The boundaries here are the cross-store thread deletion saga and the queue of
continuations waiting behind a run's in-flight turn; both are re-exported as
the package's public surface.
"""

from __future__ import annotations

from .continuation_queue import (
    ContinuationQueueLimits,
    QueuedContinuation,
    QueuedContinuationDisposition,
    QueuedContinuationRequest,
    reserve_queued_continuation,
    run_lifetime_deadline,
    served_continuation_queue_limits,
)
from .deletion_saga import (
    CleanupItem,
    CleanupItemResult,
    CleanupItemState,
    DeletionSaga,
    FinalizeOutcome,
    advance_deletion_cleanup_item,
    claim_deletion_saga,
    create_deletion_saga,
    deserialize_manifest,
    deserialize_results,
    finalize_deletion_saga,
    manifest_is_complete,
    serialize_manifest,
    serialize_results,
)

__all__ = [
    "CleanupItem",
    "CleanupItemResult",
    "CleanupItemState",
    "ContinuationQueueLimits",
    "DeletionSaga",
    "FinalizeOutcome",
    "QueuedContinuation",
    "QueuedContinuationDisposition",
    "QueuedContinuationRequest",
    "advance_deletion_cleanup_item",
    "claim_deletion_saga",
    "create_deletion_saga",
    "deserialize_manifest",
    "deserialize_results",
    "finalize_deletion_saga",
    "manifest_is_complete",
    "reserve_queued_continuation",
    "run_lifetime_deadline",
    "serialize_manifest",
    "serialize_results",
    "served_continuation_queue_limits",
]
