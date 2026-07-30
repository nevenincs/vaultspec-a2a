"""Control-plane persistence boundaries for durable orchestration sagas.

These repositories own the control-owned durable state that coordinates work
spanning more than one store. Unlike the row-level repositories in
:mod:`vaultspec_a2a.database`, they encode control-plane lifecycle rules -
idempotent creation, claiming, advancement, and finalization - over that state.

The first such boundary is the cross-store thread deletion saga, whose
operations are re-exported here as the package's public surface.
"""

from __future__ import annotations

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
    "DeletionSaga",
    "FinalizeOutcome",
    "advance_deletion_cleanup_item",
    "claim_deletion_saga",
    "create_deletion_saga",
    "deserialize_manifest",
    "deserialize_results",
    "finalize_deletion_saga",
    "manifest_is_complete",
    "serialize_manifest",
    "serialize_results",
]
