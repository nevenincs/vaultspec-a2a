"""WebSocket dispatch handler factories (ADR-019).

Creates the message and control handlers that bridge WebSocket commands
to the worker process via ``control.dispatch``.  These are protocol
translation functions: they map WS-specific error codes and rejection
semantics onto the generic dispatch pipeline.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from ..control.diagnostics import classify_missing_ws_thread, mark_thread_failed
from ..control.dispatch import (
    WorkerAtCapacityError,
    WorkerCircuitOpenError,
    WorkerUnreachableError,
    dispatch_to_worker,
)
from ..database.crud import ThreadStatus, get_thread
from ..ipc.schemas import DispatchRequest
from ._utils import trace_headers
from .schemas.enums import AgentControlAction
from .websocket import WebSocketCommandRejectedError

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from ..control.circuit_breaker import WorkerCircuitBreaker
    from ..control.worker_management import LazyWorkerSpawner

__all__ = [
    "create_dispatch_control_handler",
    "create_dispatch_message_handler",
]

logger = logging.getLogger(__name__)


async def _raise_missing_thread(
    *,
    thread_id: str,
    session_factory: Any,
    checkpointer: Any,
) -> WebSocketCommandRejectedError:
    """Classify a missing thread and return a WS rejection error.

    Delegates DB/checkpoint inspection to ``control.diagnostics`` and
    wraps the result as a ``WebSocketCommandRejectedError``.
    """
    result = await classify_missing_ws_thread(
        thread_id=thread_id,
        session_factory=session_factory,
        checkpointer=checkpointer,
    )
    return WebSocketCommandRejectedError(
        thread_id=result.thread_id,
        code=result.code,
        message=result.message,
        recoverable=result.recoverable,
        metadata=result.metadata,
    )


async def _ws_mark_failed_and_broadcast(
    thread_id: str,
    session_factory: Any,
    connection_manager: Any,
    error_detail: str,
) -> None:
    """Mark a thread FAILED and broadcast a terminal WS event.

    DB update is delegated to ``control.diagnostics.mark_thread_failed``;
    the WS broadcast stays in the API layer.
    """
    await mark_thread_failed(thread_id, session_factory)
    terminal_payload = {
        "event_type": "thread_terminal",
        "thread_id": thread_id,
        "status": "failed",
        "error_detail": error_detail,
    }
    try:
        await connection_manager.broadcast_to_thread(thread_id, terminal_payload)
    except Exception:
        logger.warning(
            "Could not broadcast terminal event for thread %s",
            thread_id,
            exc_info=True,
        )


def create_dispatch_message_handler(
    worker_client: httpx.AsyncClient,
    session_factory: Any,
    checkpointer: Any,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    connection_manager: Any,
    app_state: Any,
) -> Callable:
    """Create message handler that dispatches to the worker process.

    Looks up the thread to forward ``team_preset`` and ``workspace_root``
    so the worker can recompile the correct graph (T26b).

    WS-G01: On dispatch failure, marks thread as FAILED in the DB and
    broadcasts a ``thread_terminal`` event so UI clients see the failure
    instead of the thread staying stuck in SUBMITTED state forever.
    """

    async def _dispatch_message(
        thread_id: str,
        content: str,
        agent_id: str | None,
    ) -> None:
        team_preset: str | None = None
        workspace_root: str | None = None
        try:
            async with session_factory() as db:
                thread = await get_thread(db, thread_id)
                if thread is None:
                    raise await _raise_missing_thread(
                        thread_id=thread_id,
                        session_factory=session_factory,
                        checkpointer=checkpointer,
                    )
                _terminal_values = (
                    ThreadStatus.COMPLETED.value,
                    ThreadStatus.FAILED.value,
                    ThreadStatus.CANCELLED.value,
                    ThreadStatus.ARCHIVED.value,
                )
                if thread.status in _terminal_values:
                    raise WebSocketCommandRejectedError(
                        thread_id=thread_id,
                        code="THREAD_TERMINAL",
                        message=(
                            f"Cannot send messages to thread in {thread.status!r} state"
                        ),
                        recoverable=False,
                    )
                if thread.status == ThreadStatus.INPUT_REQUIRED.value:
                    raise WebSocketCommandRejectedError(
                        thread_id=thread_id,
                        code="THREAD_INPUT_REQUIRED",
                        message=(
                            "Cannot send a follow-up message while the"
                            " thread is paused for input"
                        ),
                        recoverable=True,
                    )
                team_preset = thread.team_preset
                if thread.thread_metadata:
                    try:
                        meta = json.loads(thread.thread_metadata)
                        workspace_root = meta.get("workspace_root")
                    except (ValueError, AttributeError):
                        pass
        except WebSocketCommandRejectedError:
            raise
        except Exception:
            logger.warning(
                "Could not look up thread %s for WS dispatch — "
                "team_preset/workspace_root will be None",
                thread_id,
                exc_info=True,
            )

        dispatch = DispatchRequest(
            action="ingest",
            thread_id=thread_id,
            agent_id=agent_id or "vaultspec-supervisor",
            content=content,
            team_preset=team_preset,
            workspace_root=workspace_root,
        )

        try:
            await dispatch_to_worker(
                worker_client,
                dispatch,
                circuit_breaker,
                worker_spawner,
                trace_headers=trace_headers(),
            )
            app_state.worker_last_heartbeat_ts = time.monotonic()
        except WorkerCircuitOpenError as exc:
            raise WebSocketCommandRejectedError(
                thread_id=thread_id,
                code="WORKER_CIRCUIT_OPEN",
                message=exc.detail,
                recoverable=True,
            ) from exc
        except WorkerAtCapacityError:
            raise WebSocketCommandRejectedError(
                thread_id=thread_id,
                code="WORKER_AT_CAPACITY",
                message="Worker at capacity — try again later",
                recoverable=True,
            ) from None
        except WorkerUnreachableError:
            await _ws_mark_failed_and_broadcast(
                thread_id,
                session_factory,
                connection_manager,
                "Worker unreachable — message not delivered",
            )

    return _dispatch_message


def create_dispatch_control_handler(
    worker_client: httpx.AsyncClient,
    session_factory: Any,
    checkpointer: Any,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    app_state: Any,
) -> Callable:
    """Create agent control handler that dispatches to the worker.

    Sends an HTTP POST to the worker's ``/dispatch`` endpoint.
    """

    async def _dispatch_control(
        thread_id: str,
        agent_id: str,
        action: AgentControlAction,
    ) -> None:
        match action:
            case AgentControlAction.TERMINATE:
                dispatch_action = "cancel"
            case AgentControlAction.RESUME:
                logger.warning(
                    "WS RESUME without option_id is a no-op;"
                    " use POST /permissions/{id}/respond"
                    " -- thread %s",
                    thread_id,
                )
                return
            case AgentControlAction.PAUSE:
                logger.info("Pause not supported -- ignoring for thread %s", thread_id)
                return

        async with session_factory() as db:
            thread = await get_thread(db, thread_id)
            if thread is None:
                raise await _raise_missing_thread(
                    thread_id=thread_id,
                    session_factory=session_factory,
                    checkpointer=checkpointer,
                )

        dispatch = DispatchRequest(
            action=dispatch_action,
            thread_id=thread_id,
            agent_id=agent_id,
        )
        try:
            await dispatch_to_worker(
                worker_client,
                dispatch,
                circuit_breaker,
                worker_spawner,
                bypass_circuit_breaker=True,
                trace_headers=trace_headers(),
            )
            app_state.worker_last_heartbeat_ts = time.monotonic()
        except (WorkerAtCapacityError, WorkerUnreachableError):
            logger.warning(
                "Failed to dispatch control to worker for thread %s",
                thread_id,
                exc_info=True,
            )

    return _dispatch_control
