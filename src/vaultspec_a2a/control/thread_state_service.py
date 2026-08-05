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

from langgraph.checkpoint.base import CheckpointTuple
from pydantic import ValidationError

from ..authoring.contract import is_document_authoring_role
from ..control.projection import (
    apply_authoring_completion_check,
    apply_checkpoint_projection,
    clear_permissions_without_checkpoint_truth,
    enrich_snapshot_from_durable_state,
    enrich_snapshot_from_execution_state,
    reconcile_checkpoint_permissions_with_durable_state,
)
from ..control.run_discovery_service import reconcile_abandoned_reconciling_thread
from ..control.snapshot import (
    MinimalState,
    enrich_snapshot_from_state,
    load_checkpoint_history_depth,
)
from ..database import get_thread
from ..graph.enums import SemanticPhase, research_adr_semantic_phase
from ..team.team_config import load_agent_config, load_team_config
from ..thread.enums import (
    RepairStatus,
    ReplayStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ..thread.errors import ConfigError
from ..thread.snapshots import (
    ThreadStateData,
    classify_transcript_availability,
    finalize_snapshot_replay_status,
    project_checkpoint_tuple,
)
from ..utils.coercion import coerce_object_mapping, coerce_string_list

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.checkpoints import Checkpointer
    from ..streaming.aggregator import EventAggregator

__all__ = [
    "SemanticContext",
    "ThreadStateCapture",
    "build_thread_state",
    "capture_thread_state",
    "project_semantic_phase",
]

logger = logging.getLogger(__name__)

# Checkpointed TeamState fields carrying the engine ids a run produced.
PROPOSAL_ID_FIELD = "authoring_proposal_ids"
CHANGESET_ID_FIELD = "authoring_changeset_ids"
ACTIVE_FEATURE_FIELD = "active_feature"
AUTHORING_SESSION_FIELD = "authoring_session_id"

# --- Semantic authoring-phase projection -------

# Terminal thread statuses map straight to a product-safe semantic phase.
_SEMANTIC_TERMINAL: dict[str, SemanticPhase] = {
    ThreadStatus.COMPLETED.value: SemanticPhase.COMPLETED,
    ThreadStatus.ARCHIVED.value: SemanticPhase.COMPLETED,
    ThreadStatus.FAILED.value: SemanticPhase.FAILED,
    ThreadStatus.CANCELLED.value: SemanticPhase.CANCELLED,
    ThreadStatus.CANCELLING.value: SemanticPhase.CANCELLED,
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


def project_semantic_phase(
    *,
    status: str,
    next_nodes: list[str],
    repair_status: str | None,
) -> SemanticPhase:
    """Project a product-safe semantic authoring phase for a run.

    Maps terminal and recovery states first, then the research_adr topology
    position (from the checkpoint's next nodes) to the document-authoring phase
    vocabulary the Rust backend consumes, so it never interprets internal
    LangGraph node names. The node-to-phase mapping is the single shared
    ``research_adr_semantic_phase`` (graph.enums) that the SSE frame stamping also
    reads. A run whose position is not a research_adr node - a coder preset, or a
    run between nodes - gets an honest generic ``running`` (or ``starting`` before
    dispatch) rather than a fabricated authoring phase.
    """
    if status in _SEMANTIC_TERMINAL:
        return _SEMANTIC_TERMINAL[status]
    if status in _RECOVERY_STATUSES or (
        repair_status is not None and repair_status in _RECOVERY_REPAIR
    ):
        return SemanticPhase.RECOVERY_REQUIRED
    for raw in next_nodes:
        phase = research_adr_semantic_phase(raw)
        if phase is not None:
            return phase
    if status == ThreadStatus.SUBMITTED.value:
        return SemanticPhase.STARTING
    return SemanticPhase.RUNNING


def _channel_values(checkpoint_tuple: CheckpointTuple) -> dict[str, object]:
    """Return the channel values of a checkpoint tuple, or an empty mapping."""
    channel_values: object = checkpoint_tuple.checkpoint.get("channel_values")
    return coerce_object_mapping(channel_values) or {}


async def read_run_snapshot(
    checkpointer: Checkpointer,
    thread_id: str,
    *,
    timeout: float = 2.0,
) -> CheckpointTuple | None:
    """Read a run's checkpoint tuple once, or ``None`` when it is unreadable.

    Every run-status field derives from one snapshot. Reading the checkpoint
    per field let a run advance between reads, so a single response could carry
    a status from one moment and a position from another - internally
    inconsistent, and worse than a stale but coherent answer.

    Non-raising, matching the derivations it feeds: a missing, timed-out, or
    unreadable checkpoint yields ``None`` and each field degrades to its own
    empty value.
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config), timeout=timeout
        )
        return (
            checkpoint_tuple if isinstance(checkpoint_tuple, CheckpointTuple) else None
        )
    except TimeoutError:
        logger.warning("Checkpoint read timed out: %s", thread_id)
        return None
    except Exception:
        logger.warning("Checkpoint read failed: %s", thread_id, exc_info=True)
        return None


def derive_run_authoring_ids(
    checkpoint_tuple: CheckpointTuple | None,
) -> tuple[list[str], list[str]]:
    """Derive ``(proposal_ids, changeset_ids)`` from an already-read snapshot."""
    if checkpoint_tuple is None:
        return [], []
    values = _channel_values(checkpoint_tuple)
    return (
        coerce_string_list(values.get(PROPOSAL_ID_FIELD), drop_empty=True) or [],
        coerce_string_list(values.get(CHANGESET_ID_FIELD), drop_empty=True) or [],
    )


def _preset_requires_document_authoring(team_preset: str | None) -> bool:
    """Return whether *team_preset* runs at least one document-authoring role.

    Deliberately role-based, not topology-based. The served
    ``authoring_capability`` projection (``team_config.authoring_capability``)
    keys on topology alone (``is_document_authoring_topology``, true only for
    ``research_adr``), which misclassifies the solo doc-editor lane: its
    topology is ``pipeline``, not ``research_adr``, so that predicate answers
    "coding" for a preset that authors documents through the engine bridge.
    Checking each worker's persona ``role`` against the authoring contract's
    role set catches both the research_adr phase machine and the solo
    doc-editor lane through one predicate, because ``DOCUMENT_AUTHORING_ROLES``
    already unions both by construction.

    Fails closed toward *not flagging*: a preset that cannot be resolved or
    whose worker configs cannot be loaded returns ``False`` rather than
    raising, so a run-status read never breaks over a config problem. An
    unloadable preset already fails run-start elsewhere (fail-closed there),
    so this module declining to guess at an unproven predicate does not mask
    that defect.
    """
    if not team_preset:
        return False
    try:
        team_config = load_team_config(team_preset)
    except (ConfigError, ValidationError):
        return False
    for worker in team_config.workers:
        try:
            agent_config = load_agent_config(worker.agent_id)
        except (ConfigError, ValidationError):
            continue
        if is_document_authoring_role(agent_config.role):
            return True
    return False


@dataclass(frozen=True, slots=True)
class SemanticContext:
    """A run's target feature and produced authoring session id (run-status)."""

    feature_tag: str | None
    authoring_session_id: str | None


@dataclass(frozen=True, slots=True)
class ThreadStateCapture:
    """One coherent durable and checkpoint-backed run-status read.

    The gateway must derive every response field from this capture.  Keeping the
    tuple with its fully reconciled snapshot prevents a second checkpoint or
    thread read from mixing different moments of a progressing run.

    ``transcript`` states whether the snapshot's messages are the run's record
    or an artefact of an unread checkpoint. It is carried here rather than
    re-derived by each reader because ``checkpoint_tuple`` alone cannot answer
    it: a ``None`` tuple is a not-yet-dispatched run, a lost checkpoint, and an
    unreachable checkpoint store all at once.
    """

    snapshot: ThreadStateData
    checkpoint_tuple: CheckpointTuple | None
    team_preset: str | None
    thread_metadata: str | None
    transcript: TranscriptAvailability


def _optional_str(value: object) -> str | None:
    """Return *value* when it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def derive_run_semantic_context(
    checkpoint_tuple: CheckpointTuple | None,
) -> SemanticContext:
    """Derive the target feature and authoring session from a read snapshot."""
    if checkpoint_tuple is None:
        return SemanticContext(feature_tag=None, authoring_session_id=None)
    values = _channel_values(checkpoint_tuple)
    return SemanticContext(
        feature_tag=_optional_str(values.get(ACTIVE_FEATURE_FIELD)),
        authoring_session_id=_optional_str(values.get(AUTHORING_SESSION_FIELD)),
    )


async def capture_thread_state(
    db: AsyncSession,
    *,
    thread_id: str,
    aggregator: EventAggregator,
    checkpointer: Checkpointer,
) -> ThreadStateCapture | None:
    """Capture a coherent thread snapshot and its successfully projected tuple.

    A single durable thread/permission read is reconciled against exactly one
    checkpoint tuple.  The tuple is exposed only after its projection succeeds,
    so consumers cannot combine a partial snapshot with untrusted checkpoint
    fields.  Does **not** raise ``HTTPException`` — the route handler owns HTTP
    response mapping.
    """
    thread = await get_thread(db, thread_id)
    if thread is None or thread.status == ThreadStatus.DELETING.value:
        # A thread under deletion is a cross-store cleanup subject, not a run.
        # Product run lookups must not surface it; the cleanup coordinator reads
        # it directly instead. Report it as absent so the route answers 404.
        return None
    if thread.status == ThreadStatus.RECONCILING.value:
        # T3's reconciler backstop (see run_discovery_service), reused here so
        # a direct single-run status read resolves an abandoned reconciling
        # thread too, not only the active-run list. `thread` is the same
        # SQLAlchemy identity-mapped row `update_thread_status` would mutate
        # (same session, same primary key), so a reconciliation performed here
        # is already reflected on `thread` below with no re-fetch needed.
        await reconcile_abandoned_reconciling_thread(db, thread_id)
    last_seq = aggregator.get_sequence(thread_id)

    snapshot = ThreadStateData(
        thread_id=thread_id,
        status=thread.status,
        last_sequence=last_seq,
        repair_status=thread.repair_status,
        execution_readiness=thread.execution_readiness,
        approval_status=thread.approval_status,
        approval_request_id=thread.approval_request_id,
        failure_reason=thread.failure_reason,
        provider_condition=thread.provider_condition,
        repair_reason=thread.repair_reason,
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
    captured_tuple: CheckpointTuple | None = None

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
            captured_tuple = checkpoint_tuple
    except TimeoutError:
        logger.warning(
            "Timed out loading checkpoint for thread %s after 10s; "
            "returning partial snapshot",
            thread_id,
        )
        checkpoint_error = True
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_timeout")
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
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
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
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

    # Gated on checkpoint_loaded, not merely captured_tuple: an unread
    # checkpoint already carries its own "unavailable" degraded reason above,
    # and asserting emptiness on top of an unread snapshot would misreport
    # "unread" as "produced nothing" - see apply_authoring_completion_check.
    if checkpoint_loaded:
        proposal_ids, changeset_ids = derive_run_authoring_ids(captured_tuple)
        snapshot = apply_authoring_completion_check(
            snapshot,
            thread_status=thread.status,
            requires_document_authoring=_preset_requires_document_authoring(
                thread.team_preset
            ),
            proposal_ids=proposal_ids,
            changeset_ids=changeset_ids,
        )

    finalized_snapshot = finalize_snapshot_replay_status(
        snapshot,
        checkpoint_loaded=checkpoint_loaded,
        checkpoint_present=checkpoint_present,
        checkpoint_error=checkpoint_error,
        thread_status=thread.status,
    )
    return ThreadStateCapture(
        snapshot=finalized_snapshot,
        checkpoint_tuple=captured_tuple,
        team_preset=thread.team_preset,
        thread_metadata=thread.thread_metadata,
        transcript=classify_transcript_availability(
            checkpoint_loaded=checkpoint_loaded,
            checkpoint_present=checkpoint_present,
            checkpoint_error=checkpoint_error,
            thread_status=thread.status,
        ),
    )


async def build_thread_state(
    db: AsyncSession,
    *,
    thread_id: str,
    aggregator: EventAggregator,
    checkpointer: Checkpointer,
) -> ThreadStateData | None:
    """Return the snapshot portion of :func:`capture_thread_state`."""
    capture = await capture_thread_state(
        db,
        thread_id=thread_id,
        aggregator=aggregator,
        checkpointer=checkpointer,
    )
    return capture.snapshot if capture is not None else None
