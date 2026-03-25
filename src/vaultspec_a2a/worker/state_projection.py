"""State projection and terminal status emission.

Extracted from ``executor.py`` (D-09) to isolate checkpoint inspection,
state normalization, and terminal event emission from the dispatch
orchestration logic in ``Executor``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from ..ipc.schemas import (
    ExecutionStateProjectionPayload,
    ExecutionTaskProjectionPayload,
)

if TYPE_CHECKING:
    from langgraph.types import StateSnapshot

    from ..database.checkpoints import Checkpointer
    from ..streaming.aggregator import StreamableGraph
    from .ipc import WorkerBridge

__all__ = ["StateProjector"]

logger = logging.getLogger(__name__)


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
            return "completed", False

        channels = {w[1] for w in pending_writes}
        if error_ch in channels:
            # Unhandled task error flushed to checkpoint before crash.
            return "failed", False
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
        state: StateSnapshot,
    ) -> ExecutionStateProjectionPayload:
        """Normalize LangGraph runtime state into a durable worker payload."""
        next_nodes = [str(node) for node in getattr(state, "next", ())]
        state_interrupts = getattr(state, "interrupts", ()) or ()
        interrupt_types: list[str] = []
        tasks: list[ExecutionTaskProjectionPayload] = []

        for task in getattr(state, "tasks", ()) or ():
            task_interrupts = getattr(task, "interrupts", ()) or ()
            interrupt_ids: list[str] = []
            task_interrupt_types: list[str] = []
            for interrupt in task_interrupts:
                interrupt_id = getattr(interrupt, "id", None)
                if interrupt_id is not None:
                    interrupt_ids.append(str(interrupt_id))
                payload = getattr(interrupt, "value", interrupt)
                if isinstance(payload, dict) and payload.get("type") is not None:
                    interrupt_type = str(payload["type"])
                    task_interrupt_types.append(interrupt_type)
                    if interrupt_type not in interrupt_types:
                        interrupt_types.append(interrupt_type)
            tasks.append(
                ExecutionTaskProjectionPayload(
                    task_id=str(getattr(task, "id", "")),
                    name=str(getattr(task, "name", "")),
                    path=[str(item) for item in getattr(task, "path", ())],
                    has_error=getattr(task, "error", None) is not None,
                    error_type=(
                        type(task.error).__name__
                        if getattr(task, "error", None) is not None
                        else None
                    ),
                    interrupt_ids=interrupt_ids,
                    interrupt_types=task_interrupt_types,
                    has_nested_state=getattr(task, "state", None) is not None,
                    has_result=getattr(task, "result", None) is not None,
                )
            )

        if state_interrupts and not interrupt_types:
            for interrupt in state_interrupts:
                payload = getattr(interrupt, "value", interrupt)
                if isinstance(payload, dict) and payload.get("type") is not None:
                    interrupt_types.append(str(payload["type"]))

        snapshot_created_at = getattr(state, "created_at", None)
        if isinstance(snapshot_created_at, datetime):
            snapshot_created_at_value: str | None = snapshot_created_at.isoformat()
        elif isinstance(snapshot_created_at, str):
            snapshot_created_at_value = snapshot_created_at
        else:
            snapshot_created_at_value = None

        state_config = getattr(state, "config", None) or {}
        parent_config = getattr(state, "parent_config", None) or {}
        return ExecutionStateProjectionPayload(
            checkpoint_id=state_config.get("configurable", {}).get("checkpoint_id"),
            parent_checkpoint_id=parent_config.get("configurable", {}).get(
                "checkpoint_id"
            ),
            snapshot_created_at=snapshot_created_at_value,
            next_nodes=next_nodes,
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
            state = await asyncio.wait_for(graph.aget_state(config), timeout=10.0)
            payload = self.normalize_execution_state(cast("StateSnapshot", state))
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
    ) -> None:
        """Emit a ``thread_terminal`` event to the gateway.

        Emits for ``"completed"``, ``"failed"``, and ``"cancelled"`` outcomes.
        ``"interrupted"`` means the graph is suspended (awaiting permission)
        and the thread should remain ``RUNNING``.

        *error_detail* is forwarded in the event payload when set, allowing
        the gateway to surface compilation/execution error messages to clients
        (WRK-K03).
        """
        if outcome not in ("completed", "failed", "cancelled"):
            return
        payload: dict[str, str] = {
            "event_type": "thread_terminal",
            "thread_id": thread_id,
            "status": outcome,
        }
        if error_detail:
            payload["error_detail"] = error_detail
        await self._bridge.send_event(thread_id, payload)
        # F-17 fix: flush terminal events immediately -- do not batch.
        # A lost thread_terminal event leaves the thread stuck in RUNNING
        # forever.  The cost is one extra HTTP POST per thread completion.
        try:
            await self._bridge.flush_events()
        except Exception:
            logger.warning(
                "Failed to flush terminal event for %s", thread_id, exc_info=True
            )
