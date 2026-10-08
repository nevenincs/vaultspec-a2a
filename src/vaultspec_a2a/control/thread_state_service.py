"""Thread state snapshot assembly service.

Assembles one run's snapshot and checkpoint projection in a testable,
transport-agnostic function.  The route handlers validate input and serve the
result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..context.metadata import ThreadMetadata
from ..database import (
    ThreadModel,
    get_thread,
    read_latest_checkpoint,
    retained_high_water_mark,
)
from ..domain_config import domain_config
from ..graph.enums import (
    ProviderCondition,
    SemanticPhase,
    research_adr_semantic_phase,
)
from ..providers.team_selection import TeamSelectionError
from ..team.team_config import AuthoringCapability, authoring_capability
from ..thread.enums import (
    DegradedReason,
    RepairStatus,
    ReplayStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ..thread.snapshots import ThreadStateSnapshot, project_checkpoint_tuple
from ..utils.coercion import (
    coerce_nonempty_str,
    coerce_string_list,
    decode_json_object,
)
from .execution_authority import (
    ExecutionAuthorityError,
    read_frozen_team_selection_from_fields,
    resolve_execution_authority_from_fields,
)
from .graph_definition import read_accepted_graph_definition
from .projection import (
    apply_authoring_completion_check,
    apply_checkpoint_projection,
    classify_transcript_availability,
    clear_permissions_without_checkpoint_truth,
    enrich_snapshot_from_durable_state,
    enrich_snapshot_from_execution_state,
    finalize_snapshot_replay_status,
    mark_degraded,
    reconcile_checkpoint_permissions_with_durable_state,
    withhold_terminal_interrupt_disclosure,
)
from .recovery_authority import (
    STORE_CONTENDED,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from .snapshot import (
    MinimalState,
    checkpoint_history_depth,
    enrich_snapshot_from_state,
)

if TYPE_CHECKING:
    from collections.abc import Collection

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import Checkpointer
    from ..providers.team_selection import FrozenTeamSelection
    from ..streaming import RelayHub, RunLiveStateMirror
    from ..thread.snapshots import CheckpointProjection

__all__ = [
    "ACTIVE_FEATURE_FIELD",
    "AUTHORING_SESSION_FIELD",
    "CHANGESET_ID_FIELD",
    "PROPOSAL_ID_FIELD",
    "capture_thread_state",
    "derive_run_authoring_ids",
    "derive_run_semantic_context",
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


def derive_run_authoring_ids(
    projection: CheckpointProjection | None,
) -> tuple[list[str], list[str]]:
    """Derive ``(proposal_ids, changeset_ids)`` from one projection."""
    if projection is None:
        return [], []
    values = projection.channel_values
    return (
        coerce_string_list(values.get(PROPOSAL_ID_FIELD), drop_empty=True) or [],
        coerce_string_list(values.get(CHANGESET_ID_FIELD), drop_empty=True) or [],
    )


async def _document_authoring_required(db: AsyncSession, thread_id: str) -> bool:
    """Return whether the run's accepted definition has a document-authoring role.

    Asked of the definition frozen when the run was accepted, never of the preset
    files as they read now: the answer is the one the run executes under, and no
    config file is loaded to give it. Role-based, through
    ``team_config.authoring_capability``, so the research_adr phase machine and the
    solo doc-editor lane are both caught by one predicate.

    Fails closed toward *not flagging*: a run whose accepted definition cannot be
    read answers ``False`` rather than raising, so a run-status read never breaks
    over it. The same unreadable definition already refuses every later graph
    action of the run, so declining to guess here does not mask that defect.
    """
    try:
        definition = await read_accepted_graph_definition(db, thread_id)
    except ValueError as exc:
        logger.warning(
            "Run %s has no readable accepted definition (%s); the authoring "
            "completion check is skipped",
            thread_id,
            exc,
        )
        return False
    team, agents, _ = definition.compiler_inputs()
    return authoring_capability(team, agents) is AuthoringCapability.DOCUMENT_AUTHORING


@dataclass(frozen=True, slots=True)
class _SemanticContext:
    """A run's target feature and produced authoring session id (run-status)."""

    feature_tag: str | None
    authoring_session_id: str | None


@dataclass(frozen=True, slots=True)
class _MetadataView:
    """A thread's stored metadata, decoded once for every reader of its capture.

    ``fields`` is the JSON object the blob holds, for the readers of one keyed
    entry, and ``provenance`` is the metadata model those fields satisfy. Both are
    ``None`` when the blob is absent or does not decode to what they name.
    """

    fields: dict[str, object] | None
    provenance: ThreadMetadata | None


@dataclass(frozen=True, slots=True)
class _ThreadStateCapture:
    """One coherent durable and checkpoint-backed run-status read.

    The gateway must derive every response field from this capture.  Keeping the
    checkpoint projection with its fully reconciled snapshot prevents a second
    checkpoint or thread read from mixing different moments of a progressing run.

    ``checkpoint_projection`` is the one projection of the checkpoint the
    snapshot was built from, present exactly when that checkpoint was read and
    projected. A field read from the checkpoint - its channel values - reads it
    rather than projecting the tuple again; the pending clarification was read
    from it once, onto the snapshot, which every surface then serves.
    ``proposal_ids`` and ``changeset_ids`` are the authoring ids that projection
    holds, derived once and empty without one.

    ``metadata`` is the thread's stored metadata, decoded once here so no reader
    parses the blob again. ``frozen_selection`` is the execution authority that
    metadata holds, validated once beside the digest the snapshot is reconciled
    against, and ``None`` whenever there is none to disclose - including a stored
    record that fails validation, which the snapshot reports as a degraded
    reason. Carried here rather than re-read at the edge because the stored bytes
    are digest-protected: a second reading of them raises, and a surface that
    raises over a field the capture already degraded over refuses the whole run.

    ``transcript`` states whether the snapshot's messages are the run's record
    or an artefact of an unread checkpoint. It is carried here rather than
    re-derived by each reader because ``checkpoint_projection`` alone cannot
    answer it: a ``None`` projection is a not-yet-dispatched run, a lost
    checkpoint, and an unreachable checkpoint store all at once.
    """

    snapshot: ThreadStateSnapshot
    checkpoint_projection: CheckpointProjection | None
    team_preset: str | None
    metadata: _MetadataView
    frozen_selection: FrozenTeamSelection | None
    proposal_ids: list[str]
    changeset_ids: list[str]
    transcript: TranscriptAvailability


def derive_run_semantic_context(
    projection: CheckpointProjection | None,
) -> _SemanticContext:
    """Derive the target feature and authoring session from one projection."""
    if projection is None:
        return _SemanticContext(feature_tag=None, authoring_session_id=None)
    values = projection.channel_values
    return _SemanticContext(
        feature_tag=coerce_nonempty_str(values.get(ACTIVE_FEATURE_FIELD)),
        authoring_session_id=coerce_nonempty_str(values.get(AUTHORING_SESSION_FIELD)),
    )


def _view_metadata(thread_id: str, text: str | None) -> _MetadataView:
    """Decode *text* once into the view every reader of the capture shares.

    Absent metadata is stored as null OR as an empty string depending on how the
    run was created, and an empty string is not parseable JSON - so the guard is
    truthiness, not "is not None".

    Unreadable metadata is reported as absent rather than failing the read. Not
    defensive padding: the stored blob and the metadata model genuinely disagree
    today - a run started without a workspace root persists metadata the model
    rejects as incomplete - and run-status and run-history report the record they
    can read rather than lose a whole read over one unrelated field.
    """
    fields = decode_json_object(text)
    provenance: ThreadMetadata | None = None
    if text:
        try:
            provenance = ThreadMetadata.model_validate(fields)
        except ValidationError:
            logger.warning(
                "Stored metadata for run %s does not satisfy the metadata model; "
                "reporting it absent",
                thread_id,
            )
    return _MetadataView(fields=fields, provenance=provenance)


@dataclass(frozen=True, slots=True)
class _CheckpointSnapshotRead:
    snapshot: ThreadStateSnapshot
    loaded: bool
    present: bool
    error: bool
    captured_projection: CheckpointProjection | None


async def _read_projected_checkpoint(
    checkpointer: Checkpointer,
    snapshot: ThreadStateSnapshot,
    mirror: RunLiveStateMirror,
    expected_assignment_digest: str | None,
    durable_permission_ids: Collection[str],
) -> _CheckpointSnapshotRead:
    thread_id = snapshot.thread_id
    checkpoint_loaded = False
    checkpoint_present = False
    checkpoint_error = False
    captured_projection: CheckpointProjection | None = None

    try:
        checkpoint_tuple = (
            await read_latest_checkpoint(checkpointer, thread_id)
        ).tuple_or_raise()
        if checkpoint_tuple is not None:
            checkpoint_present = True
            # Read off the tuple above, so there is no second listing to time
            # out or fail and no degradation this read can report.
            history_depth = checkpoint_history_depth(checkpoint_tuple)
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
                mirror=mirror,
                expected_assignment_digest=expected_assignment_digest,
            )
            snapshot = apply_checkpoint_projection(snapshot, projection)
            snapshot = reconcile_checkpoint_permissions_with_durable_state(
                snapshot,
                projection,
                durable_permission_ids=durable_permission_ids,
            )
            checkpoint_loaded = True
            captured_projection = projection
    except TimeoutError:
        checkpoint_error = True
        mark_degraded(
            snapshot,
            DegradedReason.CHECKPOINT_TIMEOUT,
            repair=RepairStatus.CHECKPOINT_UNAVAILABLE,
        )
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
        snapshot = clear_permissions_without_checkpoint_truth(snapshot)
    except Exception:
        logger.warning(
            "Could not load checkpoint for thread %s; returning partial snapshot",
            thread_id,
            exc_info=True,
        )
        checkpoint_error = True
        mark_degraded(
            snapshot,
            DegradedReason.CHECKPOINT_UNAVAILABLE,
            repair=RepairStatus.CHECKPOINT_UNAVAILABLE,
        )
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
        snapshot = clear_permissions_without_checkpoint_truth(snapshot)

    return _CheckpointSnapshotRead(
        snapshot=snapshot,
        loaded=checkpoint_loaded,
        present=checkpoint_present,
        error=checkpoint_error,
        captured_projection=captured_projection,
    )


async def _served_last_sequence(
    db: AsyncSession, thread: ThreadModel, relay_hub: RelayHub
) -> int:
    """Return the run's frame cursor: the highest number its stream has issued.

    The durable column wins once it exists: settle wrote it from the sequence
    allocator, and a settled run is never revived, so no later turn moves it.
    Otherwise the allocator's issued mark answers, then the retained window's
    greatest sequence - the mark a restarted gateway seeds its numbering from,
    so a restart does not rewind the cursor - then 0, the honest answer for a
    run no allocator numbered.
    """
    if thread.last_sequence is not None:
        return thread.last_sequence
    issued = relay_hub.issued_sequence(thread.id)
    if issued is not None:
        return issued
    return await retained_high_water_mark(db, thread.id) or 0


async def capture_thread_state(
    db: AsyncSession,
    *,
    thread_id: str,
    relay_hub: RelayHub,
    checkpointer: Checkpointer,
) -> _ThreadStateCapture | None:
    """Capture a coherent thread snapshot and its checkpoint projection.

    A single durable thread/permission read is reconciled against exactly one
    checkpoint tuple.  Its projection is exposed only once the snapshot has been
    built from it, so consumers cannot combine a partial snapshot with untrusted
    checkpoint fields.  Does **not** raise ``HTTPException`` — the route handler
    owns HTTP response mapping.
    """
    thread = await get_thread(db, thread_id)
    if thread is None or thread.status == ThreadStatus.DELETING.value:
        # A thread under deletion is a cross-store cleanup subject, not a run.
        # Product run lookups must not surface it; the cleanup coordinator reads
        # it directly instead. Report it as absent so the route answers 404.
        return None
    observation = await reconcile_run_checkpoint(
        db,
        checkpointer,
        RecoveryRequest(
            thread_id=thread_id,
            checkpoint_timeout_seconds=domain_config.aget_state_timeout_seconds,
            trigger=RecoveryTrigger.READ,
        ),
    )
    await db.commit()
    thread = await get_thread(db, thread_id, refresh=True)
    if thread is None or thread.status == ThreadStatus.DELETING.value:
        return None
    snapshot = ThreadStateSnapshot(
        thread_id=thread_id,
        status=ThreadStatus(thread.status),
        last_sequence=await _served_last_sequence(db, thread, relay_hub),
        failure_reason=thread.failure_reason,
        # Resolved to its member here rather than carried as the stored string:
        # the read model declares the vocabulary, and the column is only ever
        # written from it, so a value outside it is store corruption and says so.
        provider_condition=(
            None
            if thread.provider_condition is None
            else ProviderCondition(thread.provider_condition)
        ),
        repair_reason=thread.repair_reason,
    )
    # Collects every request id a durable row exists for, disclosed or withheld
    # alike, so the checkpoint reconciliation below never reports a row that
    # exists but was withheld as having no durable row at all. Without it the
    # withholding reason and the orphan reason both fired for one fault, and
    # only the second one sends an operator looking for lost data.
    durable_permission_ids: set[str] = set()
    snapshot = await enrich_snapshot_from_durable_state(
        db,
        thread=thread,
        snapshot=snapshot,
        durable_permission_ids=durable_permission_ids,
    )
    if observation.condition == STORE_CONTENDED:
        # The read's product is the truth about the run, and the row above is
        # that truth: the refused settlement applied nothing, so the status
        # served is the run's own durable state and this names the advance it is
        # still owed. Disclosed rather than refused because the settlement is
        # the recovery coordinator's work, not this read's - failing the whole
        # response would cost the caller the record it asked for over a store
        # condition that resolves by itself, which is what the 500 on run-status
        # and run-history did. No repair posture: nothing about the run is
        # damaged, and the next pass writes what this one proved.
        mark_degraded(snapshot, DegradedReason.SETTLEMENT_STORE_CONTENDED)
    metadata = _view_metadata(thread_id, thread.thread_metadata)
    try:
        expected_assignment_digest = resolve_execution_authority_from_fields(
            metadata.fields
        ).model_assignment_digest
        # Read in the SAME attempt as the digest above: both are the one stored
        # record, so one reason covers every way it fails and no later surface
        # has to re-validate bytes this read already judged.
        frozen_selection = read_frozen_team_selection_from_fields(metadata.fields)
    except (ExecutionAuthorityError, TeamSelectionError):
        expected_assignment_digest = None
        frozen_selection = None
        mark_degraded(snapshot, DegradedReason.INCOMPATIBLE_EXECUTION_AUTHORITY)
    checkpoint_read = await _read_projected_checkpoint(
        checkpointer,
        snapshot,
        relay_hub.mirror,
        expected_assignment_digest,
        durable_permission_ids,
    )
    snapshot = checkpoint_read.snapshot
    checkpoint_loaded = checkpoint_read.loaded
    checkpoint_present = checkpoint_read.present
    checkpoint_error = checkpoint_read.error
    captured_projection = checkpoint_read.captured_projection

    if not checkpoint_present:
        snapshot = clear_permissions_without_checkpoint_truth(snapshot)

    # Both halves of the run's interrupt state have landed, so this is the one
    # place a settled run's disclosure is withdrawn. Every surface serving this
    # capture - run-status and run-history alike - reads the gated snapshot.
    snapshot = withhold_terminal_interrupt_disclosure(
        snapshot, thread_status=thread.status
    )

    snapshot = await enrich_snapshot_from_execution_state(
        db,
        thread=thread,
        snapshot=snapshot,
        checkpoint_present=checkpoint_present,
        checkpoint_id=snapshot.checkpoint_id,
    )

    proposal_ids, changeset_ids = derive_run_authoring_ids(captured_projection)
    # Gated on checkpoint_loaded, not merely captured_projection: an unread
    # checkpoint already carries its own "unavailable" degraded reason above,
    # and asserting emptiness on top of an unread snapshot would misreport
    # "unread" as "produced nothing" - see apply_authoring_completion_check.
    if checkpoint_loaded:
        snapshot = apply_authoring_completion_check(
            snapshot,
            thread_status=thread.status,
            requires_document_authoring=await _document_authoring_required(
                db, thread_id
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
    return _ThreadStateCapture(
        snapshot=finalized_snapshot,
        checkpoint_projection=captured_projection,
        team_preset=thread.team_preset,
        metadata=metadata,
        frozen_selection=frozen_selection,
        proposal_ids=proposal_ids,
        changeset_ids=changeset_ids,
        transcript=classify_transcript_availability(
            checkpoint_loaded=checkpoint_loaded,
            checkpoint_present=checkpoint_present,
            checkpoint_error=checkpoint_error,
            thread_status=thread.status,
        ),
    )
