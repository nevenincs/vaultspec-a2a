"""WebSocket dispatch handler factories (ADR-019).

Creates the message and control handlers that bridge WebSocket commands
to the service layer.  These are protocol translation functions: they map
service-layer result objects to WS-specific error codes and rejection
semantics.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ..control.cancel_service import cancel_thread
from ..control.diagnostics import classify_missing_ws_thread, mark_thread_failed
from ..control.message_service import send_followup_message
from ..domain_config import domain_config
from ..thread.dispatch_policy import FailureType
from ..thread.enums import ThreadStatus
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
        "status": ThreadStatus.FAILED,
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


def _raise_message_failure(
    thread_id: str,
    failure_type: FailureType | None,
    error_detail: str | None,
) -> WebSocketCommandRejectedError:
    """Map a ``MessageResult`` failure to a WS rejection error."""
    detail = error_detail or "Message dispatch failed"

    if failure_type == FailureType.CIRCUIT_OPEN:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="WORKER_CIRCUIT_OPEN",
            message=detail,
            recoverable=True,
        )
    if failure_type == FailureType.AT_CAPACITY:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="WORKER_AT_CAPACITY",
            message=detail,
            recoverable=True,
        )
    if failure_type == FailureType.UNREACHABLE:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="WORKER_UNREACHABLE",
            message=detail,
            recoverable=False,
        )
    if failure_type == FailureType.REJECTED:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="WORKER_REJECTED",
            message=detail,
            recoverable=False,
        )

    # Domain-level rejections via typed failure_type
    if failure_type == FailureType.NOT_FOUND:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="THREAD_NOT_FOUND",
            message=detail,
            recoverable=False,
        )
    if failure_type == FailureType.INPUT_REQUIRED:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="THREAD_INPUT_REQUIRED",
            message=detail,
            recoverable=True,
        )
    if failure_type == FailureType.TERMINAL:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="THREAD_TERMINAL",
            message=detail,
            recoverable=False,
        )

    return WebSocketCommandRejectedError(
        thread_id=thread_id,
        code="DISPATCH_FAILED",
        message=detail,
        recoverable=False,
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
    """Create message handler that delegates to the message service.

    The service layer handles thread lookup, idempotency, control-action
    creation, repair-state transitions, and dispatch.  This handler maps
    the service result to WS-specific error semantics.

    WS-G01: On unreachable/rejected failures the service marks the thread
    FAILED; we additionally broadcast a ``thread_terminal`` WS event so
    UI clients see the failure immediately.
    """

    async def _dispatch_message(
        thread_id: str,
        content: str,
        agent_id: str | None,
    ) -> None:
        async with session_factory() as db:
            result = await send_followup_message(
                db,
                thread_id=thread_id,
                content=content,
                agent_id=agent_id or "",
                idempotency_key=None,
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                worker_client=worker_client,
                recursion_limit=domain_config.graph_recursion_limit,
                trace_headers=trace_headers(),
            )

        if result.dispatched:
            app_state.worker_last_heartbeat_ts = time.monotonic()
            return

        if result.error_detail is not None or result.failure_type is not None:
            # Broadcast terminal WS event for failures that mark the thread FAILED
            if result.failure_type in (FailureType.UNREACHABLE, FailureType.REJECTED):
                await _ws_mark_failed_and_broadcast(
                    thread_id,
                    session_factory,
                    connection_manager,
                    result.error_detail or "Worker dispatch failed",
                )
                return

            if result.failure_type == FailureType.NOT_FOUND:
                raise await _raise_missing_thread(
                    thread_id=thread_id,
                    session_factory=session_factory,
                    checkpointer=checkpointer,
                )

            raise _raise_message_failure(
                thread_id, result.failure_type, result.error_detail
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
    """Create agent control handler that delegates to the cancel service.

    TERMINATE dispatches through the cancel service.  RESUME and PAUSE
    remain WS-specific stubs.
    """

    async def _dispatch_control(
        thread_id: str,
        agent_id: str,
        action: AgentControlAction,
    ) -> None:
        match action:
            case AgentControlAction.TERMINATE:
                logger.info(
                    "TERMINATE requested by agent %s for thread %s",
                    agent_id,
                    thread_id,
                )
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
            result = await cancel_thread(
                db,
                thread_id=thread_id,
                idempotency_key=None,
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                worker_client=worker_client,
                recursion_limit=domain_config.graph_recursion_limit,
                trace_headers=trace_headers(),
            )

        if result.cancelled:
            app_state.worker_last_heartbeat_ts = time.monotonic()
            return

        if result.failure_type == FailureType.NOT_FOUND:
            raise await _raise_missing_thread(
                thread_id=thread_id,
                session_factory=session_factory,
                checkpointer=checkpointer,
            )

        if result.failure_type is not None:
            logger.warning(
                "Cancel dispatch failed for thread %s: %s",
                thread_id,
                result.error_detail,
            )

    return _dispatch_control
