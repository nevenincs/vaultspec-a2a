"""State projection and terminal status emission.

Extracted from ``executor.py`` to isolate checkpoint inspection,
state normalization, and terminal event emission from the dispatch
orchestration logic in ``Executor``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard

from pydantic import TypeAdapter, ValidationError

from ..domain_config import domain_config
from ..ipc.schemas import (
    ExecutionStateProjectionPayload,
    ExecutionTaskProjectionPayload,
)
from ..providers import ProviderCondition
from ..thread.enums import TERMINAL_STATUSES, ThreadStatus

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..database.checkpoints import Checkpointer
    from ..streaming.aggregator import StreamableGraph
    from .ipc import WorkerBridge

__all__ = ["StateProjector"]

logger = logging.getLogger(__name__)
_OBJECT_MAPPING = TypeAdapter(dict[str, object])


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


def _object_mapping(value: object) -> Mapping[str, object] | None:
    """Narrow unstructured LangGraph metadata to an object-keyed mapping."""
    try:
        return _OBJECT_MAPPING.validate_python(value)
    except ValidationError:
        return None


def _interrupt_type(interrupt: object) -> str | None:
    """Return the declared interrupt type when LangGraph supplies one."""
    payload = _object_mapping(getattr(interrupt, "value", interrupt))
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


def _task_projection(
    task: object,
) -> tuple[ExecutionTaskProjectionPayload, list[str]]:
    """Project one pending LangGraph task and retain its interrupt types."""
    interrupt_ids, interrupt_types = _interrupt_details(
        getattr(task, "interrupts", ()) or ()
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
) -> tuple[list[ExecutionTaskProjectionPayload], list[str]]:
    """Project every pending task while preserving first-seen interrupt order."""
    tasks: list[ExecutionTaskProjectionPayload] = []
    interrupt_types: list[str] = []
    for task in state_tasks:
        projection, task_interrupt_types = _task_projection(task)
        tasks.append(projection)
        for interrupt_type in task_interrupt_types:
            if interrupt_type not in interrupt_types:
                interrupt_types.append(interrupt_type)
    return tasks, interrupt_types


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
    configurable_metadata = _object_mapping(configurable)
    if configurable_metadata is None or not isinstance(configurable, Mapping):
        raise TypeError("Checkpoint configurable metadata must be a mapping")
    checkpoint_id = configurable_metadata.get("checkpoint_id")
    return str(checkpoint_id) if checkpoint_id is not None else None


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
        self._log_extra_fn = log_extra_fn or (lambda **kw: kw)

    # ------------------------------------------------------------------
    # Pre-flight checkpoint inspection (reconciliation window guard)
    # ------------------------------------------------------------------

    async def pre_flight_checkpoint(
        self,
        thread_id: str,
        *,
        thread_known: bool,
    ) -> tuple[str | None, bool]:
        """Inspect the latest checkpoint before running an ingest.

        Resolves the reconciliation window gap: after a worker restart the
        gateway moves non-terminal threads to ``RECONCILING`` and re-dispatches
        them.  If the thread actually completed or errored *before* the crash
        (checkpoint was written but the DB update was lost), LangGraph would
        silently start another generation.  Inspecting the checkpoint first
        lets us detect and short-circuit these cases.

        Also corrects ``is_first_ingest``: after a restart the in-memory cache
        is empty so every dispatch looks like a first ingest, which would pass
        initial-state fields (``active_agent``, ``artifacts``, ``current_plan``)
        and overwrite accumulated checkpoint values.  Using checkpoint truth
        prevents that overwrite.

        Parameters
        ----------
        thread_id:
            The thread to inspect.
        thread_known:
            ``True`` when the thread is already tracked in the graph cache.
            Used as fallback when checkpoint inspection fails.

        Returns
        -------
        ``(outcome, is_first_ingest)`` where *outcome* is one of:

        * ``None``           -- proceed normally with ingest
        * ``"completed"``    -- graph ran to END before crash; emit and skip
        * ``"failed"``       -- unhandled error before crash; emit and skip
        * ``"interrupted"``  -- graph paused at ``interrupt()``; skip and
                                await a resume dispatch

        *is_first_ingest* is ``True`` only when no prior checkpoint row
        exists (``aget_tuple`` returns ``None``).
        """
        # Sentinel channel constants from langgraph.checkpoint.serde.types.
        interrupt_ch = "__interrupt__"
        error_ch = "__error__"

        try:
            checkpoint_tuple = await asyncio.wait_for(
                self._checkpointer.aget_tuple(
                    {"configurable": {"thread_id": thread_id}}
                ),
                timeout=5.0,
            )
        except Exception:
            logger.warning(
                "Could not inspect checkpoint for thread %s before ingest"
                " — falling back to in-memory heuristic",
                thread_id,
                exc_info=True,
                extra=self._log_extra_fn(
                    thread_id=thread_id,
                    action="checkpoint_preflight_fallback",
                    fallback_strategy="in_memory_heuristic",
                ),
            )
            is_first_ingest = not thread_known
            return None, is_first_ingest

        if checkpoint_tuple is None:
            # No prior checkpoint -- genuinely new thread.
            return None, True

        pending_writes = checkpoint_tuple.pending_writes or []
        if not pending_writes:
            # Empty pending_writes: graph ran to END cleanly before crash.
            return ThreadStatus.COMPLETED, False

        channels = {w[1] for w in pending_writes}
        if error_ch in channels:
            # Unhandled task error flushed to checkpoint before crash.
            return ThreadStatus.FAILED, False
        if interrupt_ch in channels:
            # Graph paused at interrupt() -- needs a resume, not a new ingest.
            return "interrupted", False

        # Normal pending task writes: thread was mid-execution.
        # LangGraph will restart from the last persisted checkpoint.
        return None, False

    # ------------------------------------------------------------------
    # State normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_execution_state(
        state: _ExecutionStateSnapshot,
    ) -> ExecutionStateProjectionPayload:
        """Normalize LangGraph runtime state into a durable worker payload."""
        state_interrupts = state.interrupts or ()
        tasks, interrupt_types = _task_projections(state.tasks or ())
        if state_interrupts and not interrupt_types:
            interrupt_types = _state_interrupt_types(state_interrupts)
        return ExecutionStateProjectionPayload(
            checkpoint_id=_checkpoint_id(state.config),
            parent_checkpoint_id=_checkpoint_id(state.parent_config),
            snapshot_created_at=_snapshot_created_at_value(state.created_at),
            next_nodes=[str(node) for node in state.next],
            interrupt_types=interrupt_types,
            interrupt_count=(
                len(state_interrupts)
                if state_interrupts
                else sum(len(task.interrupt_ids) for task in tasks)
            ),
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
            payload = self.normalize_execution_state(state)
        except TimeoutError:
            payload = ExecutionStateProjectionPayload(
                degraded_reasons=["execution_state_projection_timeout"]
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
                degraded_reasons=["execution_state_projection_unavailable"]
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
        payload: dict[str, str] = {
            "event_type": "thread_terminal",
            "thread_id": thread_id,
            "status": outcome,
        }
        if error_detail:
            payload["error_detail"] = error_detail
        if outcome == ThreadStatus.FAILED:
            payload["provider_condition"] = (
                provider_condition or ProviderCondition.UNKNOWN
            ).value
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
