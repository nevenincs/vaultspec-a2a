"""State projection and terminal status emission.

Extracted from ``executor.py`` to isolate checkpoint inspection,
state normalization, and terminal event emission from the dispatch
orchestration logic in ``Executor``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, cast

from ..domain_config import domain_config
from ..graph.enums import StreamFrameKind
from ..ipc.schemas import (
    ExecutionStateProjectionPayload,
    ExecutionTaskProjectionPayload,
)
from ..providers import ProviderCondition
from ..thread.cancellation_evidence import CancellationEvidence
from ..thread.checkpoint_evidence import (
    CheckpointEvidenceKind,
    read_checkpoint_evidence,
)
from ..thread.enums import TERMINAL_STATUSES, DegradedReason, ThreadStatus
from ..thread.failure_evidence import GraphFailureEvidence, failure_detail_fingerprint
from ..thread.snapshots import tasks_past_their_interrupt
from ..utils.coercion import coerce_object_mapping

if TYPE_CHECKING:
    from ..database.checkpoints import Checkpointer
    from ..streaming.types import StreamableGraph
    from ..thread.action_receipts import GraphActionReceipt
    from .graph_lifecycle import RegisteredCompiledGraph
    from .ipc import WorkerBridge

__all__ = [
    "ResumeAdmission",
    "ResumeRefusal",
    "ResumeRefusalCause",
    "StateProjector",
]

logger = logging.getLogger(__name__)


class ResumeRefusalCause(StrEnum):
    """Why a resume must not be handed to the graph."""

    NOT_PARKED = "resume_not_parked"
    REQUEST_NOT_PENDING = "resume_request_not_pending"
    STATE_UNREADABLE = "resume_state_unreadable"
    AMBIGUOUS_TARGET = "resume_target_ambiguous"


@dataclass(frozen=True, slots=True)
class ResumeRefusal:
    """One refused resume, on the operator's channel and the client's.

    Attributes:
        cause: The vocabulary term a consumer branches on.
        detail: What the client is told, without the run identifier it is
            already looking at.
        pending_request_ids: The requests the run is actually waiting on, for
            the operator's log. Empty when the run is waiting on none, or when
            its state could not be read.
    """

    cause: ResumeRefusalCause
    detail: str
    pending_request_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResumeAdmission:
    """How one admitted resume must be handed to the graph.

    Attributes:
        interrupt_id: The interrupt this answer belongs to, when the run is
            waiting on more than one. LangGraph refuses a bare value while
            several are pending, because a bare value says nothing about which
            of them it answers, so the answer is addressed to its interrupt
            instead. ``None`` when exactly one is pending and the plain value
            is unambiguous.
    """

    interrupt_id: str | None = None


def answered_request_id(resume_value: object) -> str | None:
    """The request a resume value names, or ``None`` when it names none.

    Every typed answer this system dispatches - a tool permission, a
    clarification resolution, a plan or document verdict - carries the
    identifier of the request it answers. A value that carries none cannot be
    matched against what the run is parked on, and only the weaker
    parked-at-all check applies to it.
    """
    if not isinstance(resume_value, dict):
        return None
    named = cast("dict[str, object]", resume_value).get("request_id")
    return named if isinstance(named, str) and named else None


def _pending_requests(interrupts: Iterable[object]) -> dict[str, str]:
    """The request each pending interrupt asks, keyed by the request id.

    The value is the interrupt's own identifier, which is how an answer is
    addressed while more than one interrupt is pending. An interrupt whose
    payload names no request, or which carries no identifier, contributes
    nothing: neither can be matched to an answer.
    """
    found: dict[str, str] = {}
    for interrupt in interrupts:
        payload = coerce_object_mapping(getattr(interrupt, "value", interrupt))
        if payload is None:
            continue
        request_id = payload.get("request_id")
        interrupt_id = getattr(interrupt, "id", None)
        if (
            isinstance(request_id, str)
            and request_id
            and isinstance(interrupt_id, str)
            and interrupt_id
        ):
            found[request_id] = interrupt_id
    return found


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    """What the latest checkpoint says an arriving ingest dispatch should do.

    Attributes:
        outcome: ``"completed"``, ``"failed"`` or ``"interrupted"`` when this
            action already reached that state and must not run again; ``None``
            when it should run.
        is_first_ingest: No checkpoint exists for the thread at all.
        resume_from_checkpoint: This action's input is already in the
            checkpoint and the run stopped part-way, so it continues from there
            with no input rather than receiving its input a second time.
        refusal: Why the dispatch must not run, when the checkpoint cannot say
            what running it would do.
    """

    outcome: str | None = None
    is_first_ingest: bool = False
    resume_from_checkpoint: bool = False
    refusal: str | None = None


# The evidence kinds that decide an ingest on their own, with nothing to log
# and nothing left to weigh. Shared instances: the decision is frozen.
_SETTLED_PREFLIGHTS: Mapping[CheckpointEvidenceKind, PreflightDecision] = {
    CheckpointEvidenceKind.ABSENT: PreflightDecision(is_first_ingest=True),
    CheckpointEvidenceKind.PRIOR_ACTION: PreflightDecision(),
    CheckpointEvidenceKind.COMPLETED: PreflightDecision(outcome=ThreadStatus.COMPLETED),
    CheckpointEvidenceKind.FAILED: PreflightDecision(outcome=ThreadStatus.FAILED),
    CheckpointEvidenceKind.INTERRUPTED: PreflightDecision(outcome="interrupted"),
}

_UNREADABLE_CHECKPOINT = PreflightDecision(
    refusal=(
        "The run's checkpoint could not be read, so the dispatch was "
        "not run: running it blind could deliver its input twice"
    )
)

_FOREIGN_CHECKPOINT = PreflightDecision(
    refusal=(
        "The run's checkpoint belongs to a different action than this "
        "dispatch, so the dispatch was not run"
    )
)


class _LogExtraFn(Protocol):
    """Callable that builds a structured-logging ``extra`` mapping."""

    def __call__(self, **kwargs: object) -> dict[str, object]: ...


class _ExecutionStateSnapshot(Protocol):
    """Read-only runtime fields consumed by execution-state normalization."""

    @property
    def next(self) -> Iterable[object]: ...

    @property
    def interrupts(self) -> Collection[object]: ...

    @property
    def tasks(self) -> Collection[object]: ...

    @property
    def created_at(self) -> object: ...

    @property
    def config(self) -> Mapping[str, object]: ...

    @property
    def parent_config(self) -> Mapping[str, object] | None: ...


def _is_execution_state_snapshot(value: object) -> TypeGuard[_ExecutionStateSnapshot]:
    """Validate the minimal projection boundary returned by a graph adapter."""
    required_attributes = (
        "next",
        "interrupts",
        "tasks",
        "created_at",
        "config",
        "parent_config",
    )
    if not all(hasattr(value, attribute) for attribute in required_attributes):
        return False
    attributes = {
        attribute: getattr(value, attribute) for attribute in required_attributes
    }
    return (
        isinstance(attributes["interrupts"], Collection)
        and isinstance(attributes["tasks"], Collection)
        and isinstance(attributes["config"], Mapping)
        and (
            attributes["parent_config"] is None
            or isinstance(attributes["parent_config"], Mapping)
        )
    )


def _interrupt_type(interrupt: object) -> str | None:
    """Return the declared interrupt type when LangGraph supplies one."""
    payload = coerce_object_mapping(getattr(interrupt, "value", interrupt))
    if payload is None:
        return None
    raw_type = payload.get("type")
    return str(raw_type) if raw_type is not None else None


def _interrupt_details(interrupts: Iterable[object]) -> tuple[list[str], list[str]]:
    """Project LangGraph interrupt objects to durable task metadata."""
    interrupt_ids: list[str] = []
    interrupt_types: list[str] = []
    for interrupt in interrupts:
        interrupt_id = getattr(interrupt, "id", None)
        if interrupt_id is not None:
            interrupt_ids.append(str(interrupt_id))
        interrupt_type = _interrupt_type(interrupt)
        if interrupt_type is not None:
            interrupt_types.append(interrupt_type)
    return interrupt_ids, interrupt_types


def _task_interrupts(task: object, answered: Collection[str]) -> tuple[object, ...]:
    """The interrupts *task* is still stopped on, dropping the ones it answered.

    A snapshot lists every interrupt write the checkpoint holds against a
    task, including one it has since run past: the superstep that would have
    cleared it has not committed. ``answered`` is read from those held writes
    and is the only thing that separates the two.
    """
    if str(getattr(task, "id", "")) in answered:
        return ()
    return tuple(getattr(task, "interrupts", ()) or ())


def _task_projection(
    task: object,
    answered: Collection[str] = (),
) -> tuple[ExecutionTaskProjectionPayload, list[str]]:
    """Project one pending LangGraph task and retain its interrupt types."""
    interrupt_ids, interrupt_types = _interrupt_details(
        _task_interrupts(task, answered)
    )
    error = getattr(task, "error", None)
    return (
        ExecutionTaskProjectionPayload(
            task_id=str(getattr(task, "id", "")),
            name=str(getattr(task, "name", "")),
            path=[str(item) for item in getattr(task, "path", ())],
            has_error=error is not None,
            error_type=type(error).__name__ if error is not None else None,
            interrupt_ids=interrupt_ids,
            interrupt_types=interrupt_types,
            has_nested_state=getattr(task, "state", None) is not None,
            has_result=getattr(task, "result", None) is not None,
        ),
        interrupt_types,
    )


def _task_projections(
    state_tasks: Iterable[object],
    answered: Collection[str] = (),
) -> tuple[list[ExecutionTaskProjectionPayload], list[str]]:
    """Project every pending task while preserving first-seen interrupt order."""
    tasks: list[ExecutionTaskProjectionPayload] = []
    interrupt_types: list[str] = []
    for task in state_tasks:
        projection, task_interrupt_types = _task_projection(task, answered)
        tasks.append(projection)
        for interrupt_type in task_interrupt_types:
            if interrupt_type not in interrupt_types:
                interrupt_types.append(interrupt_type)
    return tasks, interrupt_types


def _parked_next_nodes(
    state_next: Iterable[object],
    tasks: Iterable[ExecutionTaskProjectionPayload],
) -> list[str]:
    """Return the nodes the run resumes at, counting every parked task.

    LangGraph leaves a task out of ``next`` once it holds a resume write, so a
    node that asks again after an answer that did not settle it is parked on a
    live interrupt yet absent from ``next``. The run still resumes at that
    node, and the phase it reports must not fall back to a generic one.
    """
    next_nodes = [str(node) for node in state_next]
    for task in tasks:
        if task.interrupt_ids and task.name and task.name not in next_nodes:
            next_nodes.append(task.name)
    return next_nodes


def _live_interrupts(
    state: _ExecutionStateSnapshot, answered: Collection[str]
) -> tuple[object, ...]:
    """The interrupts the run is still stopped on, across every pending task.

    ``state.interrupts`` is the union of the held interrupt writes, so it
    keeps listing the question a fanned-out branch already answered. Each
    interrupt is attributed to its task instead, and the tasks the held writes
    show finished are dropped. A snapshot with no tasks to attribute to is
    read as it stands.
    """
    tasks = tuple(state.tasks or ())
    if not tasks:
        return tuple(state.interrupts or ())
    return tuple(
        interrupt for task in tasks for interrupt in _task_interrupts(task, answered)
    )


def _addressed_admission(
    interrupts: tuple[object, ...], resume_value: object
) -> ResumeRefusal | ResumeAdmission:
    """Which of the run's open questions this answer is admitted against.

    An answer is spent on exactly the question it names. A run waiting on one
    question takes a bare value; a run waiting on several refuses one, because
    a bare value says nothing about which of them it answers and LangGraph
    would hand it to whichever interrupt the next superstep reaches first.
    """
    if not interrupts:
        return ResumeRefusal(
            cause=ResumeRefusalCause.NOT_PARKED,
            detail=(
                "The run is not waiting on a question, so the answer was not applied"
            ),
        )
    pending = _pending_requests(interrupts)
    named = answered_request_id(resume_value)
    if named is not None and named not in pending:
        return ResumeRefusal(
            cause=ResumeRefusalCause.REQUEST_NOT_PENDING,
            detail=(
                "The answer names a request the run is not waiting on, so "
                "it was not applied"
            ),
            pending_request_ids=tuple(pending),
        )
    if len(interrupts) == 1:
        return ResumeAdmission()
    if named is None:
        return ResumeRefusal(
            cause=ResumeRefusalCause.AMBIGUOUS_TARGET,
            detail=(
                "The run is waiting on more than one question and the "
                "answer names none of them, so it was not applied"
            ),
            pending_request_ids=tuple(pending),
        )
    return ResumeAdmission(interrupt_id=pending[named])


def _state_interrupt_types(interrupts: Iterable[object]) -> list[str]:
    """Project state-level interrupts when tasks carry no type metadata."""
    return [
        interrupt_type
        for interrupt in interrupts
        if (interrupt_type := _interrupt_type(interrupt)) is not None
    ]


def _snapshot_created_at_value(created_at: object) -> str | None:
    """Serialize LangGraph's timestamp variants for the wire payload."""
    if isinstance(created_at, datetime):
        return created_at.isoformat()
    if isinstance(created_at, str):
        return created_at
    return None


def _checkpoint_id(config: Mapping[str, object] | None) -> str | None:
    """Read a checkpoint identifier from a LangGraph runnable config."""
    if config is None:
        return None
    configurable = config.get("configurable")
    if configurable is None:
        return None
    if not isinstance(configurable, Mapping):
        raise TypeError("Checkpoint configurable metadata must be a mapping")
    configurable = cast("Mapping[str, object]", configurable)
    # The canonical narrower is strict, so it refuses a Mapping that is not a
    # dict. This site is the one place that must not inherit that refusal: it
    # already tested for Mapping rather than dict, which is a statement that a
    # LangGraph config may arrive as one, and letting the strict refusal reach
    # the raise above would report "must be a mapping" about a value that is a
    # mapping. Widening explicitly here keeps the tolerance visible instead of
    # hiding it inside a lenient shared narrower every other caller would then
    # silently inherit.
    configurable_metadata = coerce_object_mapping(dict(configurable))
    if configurable_metadata is None:
        raise TypeError("Checkpoint configurable metadata must be string-keyed")
    checkpoint_id = configurable_metadata.get("checkpoint_id")
    return str(checkpoint_id) if checkpoint_id is not None else None


def _validate_terminal_evidence_kind(
    outcome: str,
    cancellation_evidence: CancellationEvidence | None,
    failure_evidence: GraphFailureEvidence | None,
) -> None:
    if cancellation_evidence is not None and outcome != ThreadStatus.CANCELLED:
        raise ValueError("cancellation evidence requires a cancelled terminal")
    if failure_evidence is not None and outcome != ThreadStatus.FAILED:
        raise ValueError("failure evidence requires a failed terminal")
    if outcome == ThreadStatus.CANCELLED and cancellation_evidence is None:
        raise ValueError("cancelled terminal requires cancellation evidence")
    if outcome == ThreadStatus.FAILED and failure_evidence is None:
        raise ValueError("failed terminal requires failure evidence")


def _failure_evidence_matches(
    thread_id: str,
    error_detail: str | None,
    condition: ProviderCondition,
    evidence: GraphFailureEvidence,
) -> bool:
    return bool(
        error_detail
        and evidence.action.thread_id == thread_id
        and evidence.detail_fingerprint == failure_detail_fingerprint(error_detail)
        and evidence.provider_condition == condition.value
    )


def _validated_terminal_evidence(
    thread_id: str,
    outcome: str,
    error_detail: str | None,
    provider_condition: ProviderCondition | None,
    evidence: CancellationEvidence | GraphFailureEvidence | None,
) -> tuple[CancellationEvidence | None, GraphFailureEvidence | None, ProviderCondition]:
    cancellation_evidence = (
        evidence if isinstance(evidence, CancellationEvidence) else None
    )
    failure_evidence = evidence if isinstance(evidence, GraphFailureEvidence) else None
    _validate_terminal_evidence_kind(outcome, cancellation_evidence, failure_evidence)
    resolved_condition = provider_condition or ProviderCondition.UNKNOWN
    if failure_evidence is not None and not _failure_evidence_matches(
        thread_id, error_detail, resolved_condition, failure_evidence
    ):
        raise ValueError("failure evidence does not match terminal payload")
    return cancellation_evidence, failure_evidence, resolved_condition


class StateProjector:
    """Handles checkpoint inspection, state normalization, and terminal events.

    Parameters
    ----------
    checkpointer:
        Shared LangGraph checkpointer for checkpoint inspection.
    bridge:
        ``WorkerBridge`` for forwarding events to the gateway.
    """

    def __init__(
        self,
        checkpointer: Checkpointer,
        bridge: WorkerBridge,
        *,
        log_extra_fn: Any = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._bridge = bridge
        self._log_extra_fn: _LogExtraFn = log_extra_fn or (lambda **kw: kw)

    # ------------------------------------------------------------------
    # Pre-flight checkpoint inspection (reconciliation window guard)
    # ------------------------------------------------------------------

    async def pre_flight_checkpoint(
        self,
        receipt: GraphActionReceipt,
        *,
        timeout_seconds: float = 5.0,
    ) -> PreflightDecision:
        """Decide from the latest checkpoint what an arriving ingest should do.

        An ingest is delivered again after a worker restart - a crash, or a
        shutdown that drained the run at a superstep boundary - so the
        checkpoint may already hold this very action. The decision is read
        from the action receipts the checkpoint carries rather than from its
        pending writes alone: an empty set of pending writes means only that
        no superstep was mid-flight, which is as true of a drained run half
        way through as of a finished one, and of an earlier turn's end.

        * No checkpoint: a new thread; run with the full first-turn input.
        * An earlier action's checkpoint: a new turn; run with this input.
        * This action's checkpoint, part-way: continue from it with no input,
          so the message is not delivered twice and finished nodes do not
          re-run.
        * This action completed, failed or parked: report that, do not re-run.
        * Unreadable or foreign to this action: refuse, because running it
          blind could deliver its input a second time.
        """
        thread_id = receipt.thread_id
        evidence = await read_checkpoint_evidence(
            self._checkpointer, receipt, timeout_seconds=timeout_seconds
        )
        kind = evidence.kind
        settled = _SETTLED_PREFLIGHTS.get(kind)
        if settled is not None:
            return settled
        if kind is CheckpointEvidenceKind.PENDING:
            logger.info(
                "Thread %s checkpoint holds this action part-way; continuing "
                "from it instead of delivering the input again",
                thread_id,
                extra=self._log_extra_fn(
                    thread_id=thread_id,
                    action="checkpoint_preflight_resume",
                    checkpoint_id=evidence.checkpoint_id,
                ),
            )
            return PreflightDecision(resume_from_checkpoint=True)
        logger.warning(
            "Thread %s checkpoint evidence is %s; refusing the ingest",
            thread_id,
            kind.value,
            extra=self._log_extra_fn(
                thread_id=thread_id,
                action="checkpoint_preflight_refused",
                evidence=kind.value,
            ),
        )
        if kind is CheckpointEvidenceKind.UNAVAILABLE:
            return _UNREADABLE_CHECKPOINT
        return _FOREIGN_CHECKPOINT

    async def pre_flight_resume(
        self,
        graph: RegisteredCompiledGraph,
        config: dict[str, Any],
        receipt: GraphActionReceipt,
        *,
        resume_value: object,
        timeout_seconds: float,
    ) -> ResumeRefusal | ResumeAdmission:
        """How this resume must reach the graph, or why it must not.

        A resume is an answer to one question the run stopped to ask. Handed to
        a run that is not stopped, LangGraph gives the value to whatever the
        next superstep interrupts on first, so an answer nobody gave for that
        question settles it - a probe approved a plan that never parked. An
        answer is therefore admitted only against the question it answers.

        Three things are decided, in order of what the run's state can prove:

        * The run is parked. The live snapshot is authoritative; when it cannot
          be read, durable checkpoint evidence deciding ``INTERRUPTED`` stands
          in for it, and anything else refuses.
        * Where the answer names a request and the snapshot could be read, one
          of the pending interrupts asks that request. An answer naming a
          request the run is not waiting on is refused rather than spent on a
          different question.
        * Which interrupt the answer is addressed to, when the run is waiting
          on more than one. A bare value is refused there rather than handed
          over: LangGraph refuses it too, but as a fault inside the run rather
          than as an answer the client can correct.

        A refusal leaves the run exactly as it was. It is not a failure of the
        run: the question is still open and a correct answer still resolves it.
        """
        snapshot = await self._resume_snapshot(
            graph, config, receipt.thread_id, timeout_seconds=timeout_seconds
        )
        if snapshot is None:
            return await self._durable_resume_refusal(
                receipt, timeout_seconds=timeout_seconds
            )
        answered = tasks_past_their_interrupt(
            await self._held_writes(snapshot.config, timeout_seconds=timeout_seconds)
        )
        return _addressed_admission(_live_interrupts(snapshot, answered), resume_value)

    async def _resume_snapshot(
        self,
        graph: RegisteredCompiledGraph,
        config: dict[str, Any],
        thread_id: str,
        *,
        timeout_seconds: float,
    ) -> _ExecutionStateSnapshot | None:
        """The run's live state, or ``None`` when it cannot stand as evidence.

        A read that failed and a read that returned something other than an
        execution-state snapshot are the same thing to the caller: the live
        state proves nothing about where the run is parked, so the durable
        checkpoint has to answer instead.
        """
        try:
            snapshot: object = await asyncio.wait_for(
                graph.aget_state(config), timeout=timeout_seconds
            )
        except Exception:
            logger.warning(
                "Thread %s live state could not be read before resuming; "
                "falling back to durable checkpoint evidence",
                thread_id,
                exc_info=True,
                extra=self._log_extra_fn(
                    thread_id=thread_id, action="resume_preflight_state_unavailable"
                ),
            )
            return None
        if not _is_execution_state_snapshot(snapshot):
            return None
        return snapshot

    async def _held_writes(
        self, config: Mapping[str, object], *, timeout_seconds: float
    ) -> tuple[object, ...]:
        """The writes the store holds against the checkpoint *config* names.

        Read from the store because a snapshot does not carry a task's resume
        writes, and those are what distinguish a question still being asked
        from one already answered. A read that fails returns nothing, which
        leaves every held interrupt reading as pending: the snapshot's own
        reading, and the one that keeps disclosing a question rather than
        stranding an answer on a momentary store failure.
        """
        try:
            stored = await asyncio.wait_for(
                self._checkpointer.aget_tuple(cast("Any", config)),
                timeout=timeout_seconds,
            )
        except Exception:
            logger.warning(
                "Checkpoint writes could not be read; every interrupt the "
                "snapshot lists will be reported as still pending",
                exc_info=True,
                extra=self._log_extra_fn(action="held_writes_unavailable"),
            )
            return ()
        if stored is None:
            return ()
        return tuple(cast("Any", stored.pending_writes) or ())

    async def _durable_resume_refusal(
        self,
        receipt: GraphActionReceipt,
        *,
        timeout_seconds: float,
    ) -> ResumeRefusal | ResumeAdmission:
        """Admit a resume on durable evidence when the live read failed.

        The checkpoint records that the run stopped at an interrupt but not
        which request it asked, so this admits the answer on the weaker
        parked-at-all proof, addressed to no interrupt in particular.
        Refusing every resume whose live state momentarily could not be read
        would strand runs that are genuinely waiting.
        """
        evidence = await read_checkpoint_evidence(
            self._checkpointer, receipt, timeout_seconds=timeout_seconds
        )
        if evidence.kind is CheckpointEvidenceKind.INTERRUPTED:
            return ResumeAdmission()
        return ResumeRefusal(
            cause=(
                ResumeRefusalCause.STATE_UNREADABLE
                if evidence.kind is CheckpointEvidenceKind.UNAVAILABLE
                else ResumeRefusalCause.NOT_PARKED
            ),
            detail=(
                "The run's state does not show it waiting on a question, so "
                "the answer was not applied"
            ),
        )

    # ------------------------------------------------------------------
    # State normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_execution_state(
        state: _ExecutionStateSnapshot,
        held_writes: Iterable[object] = (),
    ) -> ExecutionStateProjectionPayload:
        """Normalize LangGraph runtime state into a durable worker payload.

        *held_writes* are the writes the checkpoint holds against this
        snapshot. They are the only thing that tells a question still being
        asked from one a fanned-out branch has already answered, because the
        snapshot lists both. Omitted, every interrupt the snapshot carries is
        read as pending, which is the snapshot's own reading of itself.
        """
        answered = tasks_past_their_interrupt(held_writes)
        state_interrupts = state.interrupts or ()
        tasks, interrupt_types = _task_projections(state.tasks or (), answered)
        interrupt_count = sum(len(task.interrupt_ids) for task in tasks)
        if state_interrupts and not tasks:
            # No task to attribute an interrupt to, so there is nothing the
            # held writes can narrow and the state-level list is the reading.
            interrupt_types = _state_interrupt_types(state_interrupts)
            interrupt_count = len(state_interrupts)
        elif interrupt_count and not interrupt_types:
            interrupt_types = _state_interrupt_types(state_interrupts)
        return ExecutionStateProjectionPayload(
            checkpoint_id=_checkpoint_id(state.config),
            parent_checkpoint_id=_checkpoint_id(state.parent_config),
            snapshot_created_at=_snapshot_created_at_value(state.created_at),
            next_nodes=_parked_next_nodes(state.next, tasks),
            interrupt_types=interrupt_types,
            interrupt_count=interrupt_count,
            task_count=len(tasks),
            tasks=tasks,
        )

    # ------------------------------------------------------------------
    # Execution state projection emission
    # ------------------------------------------------------------------

    async def emit_execution_state_projection(
        self,
        thread_id: str,
        graph: StreamableGraph,
        config: dict[str, Any],
    ) -> None:
        """Emit latest runtime execution-state truth over the internal event path."""
        try:
            state = await asyncio.wait_for(
                graph.aget_state(config),
                timeout=domain_config.aget_state_timeout_seconds,
            )
            if not _is_execution_state_snapshot(state):
                raise TypeError("Graph returned an incomplete execution-state snapshot")
            payload = self.normalize_execution_state(
                state,
                await self._held_writes(
                    state.config,
                    timeout_seconds=domain_config.aget_state_timeout_seconds,
                ),
            )
        except TimeoutError:
            payload = ExecutionStateProjectionPayload(
                degraded_reasons=[
                    DegradedReason.EXECUTION_STATE_PROJECTION_TIMEOUT.value
                ]
            )
        except Exception:
            logger.warning(
                "Failed to inspect execution state for thread %s",
                thread_id,
                exc_info=True,
                extra=self._log_extra_fn(
                    thread_id=thread_id,
                    action="execution_state_projection_failed",
                ),
            )
            payload = ExecutionStateProjectionPayload(
                degraded_reasons=[
                    DegradedReason.EXECUTION_STATE_PROJECTION_UNAVAILABLE.value
                ]
            )
        await self._bridge.send_event(thread_id, payload.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Terminal status relay
    # ------------------------------------------------------------------

    async def emit_terminal_status(
        self,
        thread_id: str,
        outcome: str,
        error_detail: str | None = None,
        *,
        provider_condition: ProviderCondition | None = None,
        evidence: CancellationEvidence | GraphFailureEvidence | None = None,
    ) -> None:
        """Emit a ``thread_terminal`` event to the gateway.

        Emits for ``"completed"``, ``"failed"``, and ``"cancelled"`` outcomes.
        ``"interrupted"`` means the graph is suspended (awaiting permission)
        and the thread should remain ``RUNNING``.

        *error_detail* is forwarded in the event payload when set, allowing
        the gateway to surface compilation/execution error messages to clients.

        *provider_condition* is its machine-readable counterpart: the detail says
        what happened, the condition says what the reader should do about it, and
        a client that has to derive the second from the first is back to matching
        vendor prose. It rides this same payload because the terminal event is
        what the gateway persists, and the error frame that also carries the
        condition is droppable - a reloading client recovers it only from here.

        A FAILED terminal ALWAYS carries a condition, defaulting to the
        vocabulary's floor. That is the invariant this campaign exists to
        establish, and it is enforced at this single emitter rather than asked of
        every call site, because a failure whose classification depends on a
        caller remembering to supply it is exactly the blank terminal being
        removed. The floor is honest at the sites that omit it: a run refused
        before any provider was engaged has no provider condition to report, and
        saying so plainly beats inventing one. Non-failed terminals carry none at
        all, since a completed or cancelled run had no provider failure to
        classify and an ``unknown`` there would read as one.
        """
        if outcome not in TERMINAL_STATUSES:
            return
        cancellation_evidence, failure_evidence, resolved_condition = (
            _validated_terminal_evidence(
                thread_id, outcome, error_detail, provider_condition, evidence
            )
        )
        payload: dict[str, object] = {
            "event_type": StreamFrameKind.THREAD_TERMINAL,
            "thread_id": thread_id,
            "status": outcome,
        }
        if error_detail:
            payload["error_detail"] = error_detail
        if outcome == ThreadStatus.FAILED:
            payload["provider_condition"] = resolved_condition.value
        if cancellation_evidence is not None:
            payload["cancellation_evidence"] = cancellation_evidence.model_dump(
                mode="json"
            )
        if failure_evidence is not None:
            payload["failure_evidence"] = failure_evidence.model_dump(mode="json")
        await self._bridge.send_event(thread_id, payload)
        # Flush terminal events immediately -- do not batch.
        # A lost thread_terminal event leaves the thread stuck in RUNNING
        # forever.  The cost is one extra HTTP POST per thread completion.
        try:
            await self._bridge.flush_events()
        except Exception:
            logger.warning(
                "Failed to flush terminal event for %s", thread_id, exc_info=True
            )
