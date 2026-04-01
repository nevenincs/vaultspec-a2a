"""WebSocket thread diagnostics for the gateway.

Contains classification logic for missing-thread WebSocket commands,
performing DB queries and checkpoint lookups to distinguish between
truly missing threads and state drift scenarios.

This module lives in ``control/`` (Layer 2 IS) because it depends on
``database`` — it cannot reside in Layer 1 (``thread/``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from ..database import (
    get_thread_execution_state,
    update_thread_status,
)
from ..thread.enums import ThreadStatus
from .repair_transitions import mark_dispatch_failed

__all__ = [
    "MissingThreadClassification",
    "classify_missing_ws_thread",
    "mark_thread_failed",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MissingThreadClassification:
    """Result of classifying why a thread is missing from the gateway DB.

    Callers use ``code`` to decide how to surface the error (e.g. as a
    ``WebSocketCommandRejectedError``).
    """

    thread_id: str
    code: str
    message: str
    recoverable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


async def classify_missing_ws_thread(
    *,
    thread_id: str,
    session_factory: Any,
    checkpointer: Any,
) -> MissingThreadClassification:
    """Classify a missing-thread WebSocket command without assuming total absence.

    Checks for residual execution state and checkpoints to distinguish:

    - ``THREAD_STATE_DRIFT``: thread row missing but backend state exists
    - ``THREAD_STATE_UNVERIFIED``: checkpoint truth could not be verified
    - ``THREAD_NOT_FOUND``: no trace of the thread anywhere
    """
    execution_state_present = False
    try:
        async with session_factory() as db:
            execution_state_present = (
                await get_thread_execution_state(db, thread_id)
            ) is not None
    except Exception:
        logger.warning(
            "Could not inspect execution-state projection for websocket thread %s",
            thread_id,
            exc_info=True,
        )

    checkpoint_present = False
    checkpoint_unverified = False
    try:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config),
            timeout=2.0,
        )
        checkpoint_present = checkpoint_tuple is not None
    except TimeoutError:
        checkpoint_unverified = True
    except Exception:
        logger.debug(
            "Could not verify checkpoint for missing thread %s",
            thread_id,
            exc_info=True,
        )
        checkpoint_unverified = True

    metadata = {
        "execution_state_present": execution_state_present,
        "checkpoint_present": checkpoint_present,
        "checkpoint_unverified": checkpoint_unverified,
    }
    if checkpoint_unverified:
        return MissingThreadClassification(
            thread_id=thread_id,
            code="THREAD_STATE_UNVERIFIED",
            message=(
                "Thread is missing from the gateway database and checkpoint truth "
                "could not be verified. Retry after the backend is healthy."
            ),
            recoverable=True,
            metadata=metadata,
        )
    if execution_state_present or checkpoint_present:
        return MissingThreadClassification(
            thread_id=thread_id,
            code="THREAD_STATE_DRIFT",
            message=(
                "Thread is missing from the gateway database, but durable backend "
                "state still exists. Refresh thread state or trigger repair before "
                "sending follow-up commands."
            ),
            recoverable=True,
            metadata=metadata,
        )
    return MissingThreadClassification(
        thread_id=thread_id,
        code="THREAD_NOT_FOUND",
        message="Thread not found.",
        recoverable=True,
        metadata=metadata,
    )


async def mark_thread_failed(
    thread_id: str,
    session_factory: Any,
) -> None:
    """Mark a thread as FAILED in the database.

    Used by WS dispatch handlers when the worker is unreachable.
    Logs but does not raise on DB errors — the caller handles
    broadcast separately.
    """
    try:
        async with session_factory() as db:
            await update_thread_status(db, thread_id, ThreadStatus.FAILED)
            await mark_dispatch_failed(
                db,
                thread_id,
                reason="Worker dispatch failed during websocket command handling",
            )
            await db.commit()
    except Exception:
        logger.warning(
            "Could not set thread %s to FAILED after WS dispatch error",
            thread_id,
            exc_info=True,
        )
