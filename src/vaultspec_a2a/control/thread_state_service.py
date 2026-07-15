"""Thread state snapshot assembly service.

Extracts the 95-line orchestration from the ``/threads/{id}/state``
endpoint into a testable, protocol-agnostic function.  The route
handler validates input and converts the result to a Pydantic wire model.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..control.projection import (
    apply_checkpoint_projection,
    clear_permissions_without_checkpoint_truth,
    enrich_snapshot_from_durable_state,
    enrich_snapshot_from_execution_state,
    reconcile_checkpoint_permissions_with_durable_state,
)
from ..control.snapshot import (
    MinimalState,
    enrich_snapshot_from_state,
    load_checkpoint_history_depth,
)
from ..database import get_thread
from ..thread.enums import RepairStatus, ThreadStatus
from ..thread.snapshots import (
    ThreadStateData,
    finalize_snapshot_replay_status,
    project_checkpoint_tuple,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.checkpoints import Checkpointer
    from ..streaming.aggregator import EventAggregator

__all__ = [
    "SemanticContext",
    "build_thread_state",
    "project_semantic_phase",
    "read_run_authoring_ids",
    "read_run_semantic_context",
]

logger = logging.getLogger(__name__)

# Checkpointed TeamState fields carrying the engine ids a run produced.
_PROPOSAL_ID_FIELD = "authoring_proposal_ids"
_CHANGESET_ID_FIELD = "authoring_changeset_ids"
_ACTIVE_FEATURE_FIELD = "active_feature"
_AUTHORING_SESSION_FIELD = "authoring_session_id"

# --- Semantic authoring-phase projection (a2a-edge-conformance P02.S04) -------

# Terminal thread statuses map straight to a product-safe semantic phase.
_SEMANTIC_TERMINAL: dict[str, str] = {
    ThreadStatus.COMPLETED.value: "completed",
    ThreadStatus.ARCHIVED.value: "completed",
    ThreadStatus.FAILED.value: "failed",
    ThreadStatus.CANCELLED.value: "cancelled",
    ThreadStatus.CANCELLING.value: "cancelled",
}

# Statuses / repair postures that mean the run needs recovery before it advances.
# Deliberate recovery states only: a transient CHECKPOINT_UNAVAILABLE on a
# freshly dispatched run (no checkpoint written yet) is normal startup, not
# recovery, so it is intentionally excluded here - genuine checkpoint loss
# transitions the thread to a recovery status through the repair machinery.
_RECOVERY_STATUSES: frozenset[str] = frozenset(
    {ThreadStatus.REPAIR_NEEDED.value, ThreadStatus.RECONCILING.value}
)
_RECOVERY_REPAIR: frozenset[str] = frozenset(
    {
        RepairStatus.NEEDS_RECONCILIATION.value,
        RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value,
    }
)

# research_adr structural node -> product-safe semantic authoring phase. The
# dispatch/researcher fan-out nodes are handled by prefix; the rest map directly.
_RESEARCH_ADR_NODE_PHASE: dict[str, str] = {
    "synthesis": "synthesizing_research",
    "research_review": "reviewing_research",
    "research_gate": "awaiting_research_decision",
    "adr_author": "writing_adr",
    "adr_review": "reviewing_adr",
    "adr_gate": "awaiting_adr_decision",
}


def project_semantic_phase(
    *,
    status: str,
    next_nodes: list[str],
    repair_status: str | None,
) -> str:
    """Project a product-safe semantic authoring phase for a run.

    Maps terminal and recovery states first, then the research_adr topology
    position (from the checkpoint's next nodes) to the document-authoring phase
    vocabulary the Rust backend consumes, so it never interprets internal
    LangGraph node names. A run whose position is not a research_adr node - a
    coder preset, or a run between nodes - gets an honest generic ``running``
    (or ``starting`` before dispatch) rather than a fabricated authoring phase.
    """
    if status in _SEMANTIC_TERMINAL:
        return _SEMANTIC_TERMINAL[status]
    if status in _RECOVERY_STATUSES or (
        repair_status is not None and repair_status in _RECOVERY_REPAIR
    ):
        return "recovery_required"
    for raw in next_nodes:
        node = raw.removeprefix("mount_")
        if not node or node == "__end__":
            continue
        if node.startswith("research_dispatch"):
            return "researching"
        phase = _RESEARCH_ADR_NODE_PHASE.get(node)
        if phase is not None:
            return phase
    if status == ThreadStatus.SUBMITTED.value:
        return "starting"
    return "running"


def _string_list(value: object) -> list[str]:
    """Return the non-empty string items of *value* when it is a list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


async def read_run_authoring_ids(
    checkpointer: Checkpointer,
    thread_id: str,
    *,
    timeout: float = 2.0,
) -> tuple[list[str], list[str]]:
    """Read a run's produced ``(proposal_ids, changeset_ids)`` from its checkpoint.

    Non-raising: a missing, timed-out, or unreadable checkpoint yields empty
    lists so the recovery snapshot degrades to "no proposals recorded" rather
    than failing the whole run-status read.
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config), timeout=timeout
        )
    except TimeoutError:
        logger.warning("Checkpoint read for authoring ids timed out: %s", thread_id)
        return [], []
    except Exception:
        logger.warning(
            "Checkpoint read for authoring ids failed: %s", thread_id, exc_info=True
        )
        return [], []
    if checkpoint_tuple is None:
        return [], []
    checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
    values = (
        checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    )
    return (
        _string_list(values.get(_PROPOSAL_ID_FIELD)),
        _string_list(values.get(_CHANGESET_ID_FIELD)),
    )


@dataclass(frozen=True, slots=True)
class SemanticContext:
    """A run's target feature and produced authoring session id (run-status)."""

    feature_tag: str | None
    authoring_session_id: str | None


def _optional_str(value: object) -> str | None:
    """Return *value* when it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


async def read_run_semantic_context(
    checkpointer: Checkpointer,
    thread_id: str,
    *,
    timeout: float = 2.0,
) -> SemanticContext:
    """Read a run's target feature and authoring session id from its checkpoint.

    Non-raising, mirroring :func:`read_run_authoring_ids`: a missing, timed-out,
    or unreadable checkpoint yields a context of ``None`` fields so run-status
    degrades gracefully rather than failing.
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config), timeout=timeout
        )
    except TimeoutError:
        logger.warning("Checkpoint read for semantic context timed out: %s", thread_id)
        return SemanticContext(feature_tag=None, authoring_session_id=None)
    except Exception:
        logger.warning(
            "Checkpoint read for semantic context failed: %s",
            thread_id,
            exc_info=True,
        )
        return SemanticContext(feature_tag=None, authoring_session_id=None)
    if checkpoint_tuple is None:
        return SemanticContext(feature_tag=None, authoring_session_id=None)
    checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
    values = (
        checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    )
    return SemanticContext(
        feature_tag=_optional_str(values.get(_ACTIVE_FEATURE_FIELD)),
        authoring_session_id=_optional_str(values.get(_AUTHORING_SESSION_FIELD)),
    )


async def build_thread_state(
    db: AsyncSession,
    *,
    thread_id: str,
    aggregator: EventAggregator,
    checkpointer: Checkpointer,
) -> ThreadStateData | None:
    """Assemble a complete thread state snapshot for client reconnection.

    Returns a ``ThreadStateData`` (Layer 1 dataclass), or ``None`` if the
    thread does not exist.  Does **not** raise ``HTTPException`` — the route
    handler owns HTTP response mapping.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return None
    last_seq = aggregator.get_sequence(thread_id)

    snapshot = ThreadStateData(
        thread_id=thread_id,
        status=thread.status,
        last_sequence=last_seq,
        repair_status=thread.repair_status,
        execution_readiness=thread.execution_readiness,
        approval_status=thread.approval_status,
        approval_request_id=thread.approval_request_id,
    )
    snapshot = await enrich_snapshot_from_durable_state(
        db, thread=thread, snapshot=snapshot
    )
    durable_permission_ids = {
        permission.request_id for permission in snapshot.pending_permissions
    }
    checkpoint_loaded = False
    checkpoint_present = False
    checkpoint_error = False

    try:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config),
            timeout=10.0,
        )
        if checkpoint_tuple is not None:
            checkpoint_present = True
            history_depth: int | None = None
            try:
                history_depth = await asyncio.wait_for(
                    load_checkpoint_history_depth(checkpointer, config),
                    timeout=10.0,
                )
            except TimeoutError:
                if "checkpoint_history_timeout" not in snapshot.degraded_reasons:
                    snapshot.degraded_reasons.append("checkpoint_history_timeout")
            except Exception:
                if "checkpoint_history_unavailable" not in snapshot.degraded_reasons:
                    snapshot.degraded_reasons.append("checkpoint_history_unavailable")
            projection = project_checkpoint_tuple(
                checkpoint_tuple,
                thread_id=thread_id,
                history_depth=history_depth,
            )

            minimal_state = MinimalState(
                values=projection.channel_values,
                cfg=projection.config,
            )
            snapshot = enrich_snapshot_from_state(
                snapshot,
                minimal_state,
                aggregator=aggregator,
            )
            snapshot = apply_checkpoint_projection(snapshot, projection)
            snapshot = reconcile_checkpoint_permissions_with_durable_state(
                snapshot,
                durable_request_ids=durable_permission_ids,
            )
            checkpoint_loaded = True
    except TimeoutError:
        logger.warning(
            "Timed out loading checkpoint for thread %s after 10s; "
            "returning partial snapshot",
            thread_id,
        )
        checkpoint_error = True
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_timeout")
        snapshot.replay_status = "unknown"
        snapshot.repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value
        snapshot.execution_readiness = RepairStatus.CHECKPOINT_UNAVAILABLE.value
        snapshot = clear_permissions_without_checkpoint_truth(snapshot)
    except Exception:
        logger.warning(
            "Could not load checkpoint for thread %s; returning partial snapshot",
            thread_id,
            exc_info=True,
        )
        checkpoint_error = True
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_unavailable")
        snapshot.replay_status = "unknown"
        snapshot.repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value
        snapshot.execution_readiness = RepairStatus.CHECKPOINT_UNAVAILABLE.value
        snapshot = clear_permissions_without_checkpoint_truth(snapshot)

    if (
        not checkpoint_loaded
        and not checkpoint_present
        and (
            thread.status != "submitted"
            or snapshot.pending_permissions
            or snapshot.approval_status is not None
            or snapshot.approval_request_id is not None
            or snapshot.pause_cause is not None
        )
    ):
        snapshot = clear_permissions_without_checkpoint_truth(snapshot)

    snapshot = await enrich_snapshot_from_execution_state(
        db,
        thread=thread,
        snapshot=snapshot,
        checkpoint_present=checkpoint_present,
        checkpoint_id=snapshot.checkpoint_id,
    )

    return finalize_snapshot_replay_status(
        snapshot,
        checkpoint_loaded=checkpoint_loaded,
        checkpoint_present=checkpoint_present,
        checkpoint_error=checkpoint_error,
        thread_status=thread.status,
    )
