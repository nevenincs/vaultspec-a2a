"""Startup entry to the shared durable recovery authority."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..database import list_non_terminal_threads
from ..domain_config import domain_config
from ..thread.enums import ThreadStatus
from .pause import reconcile_run_pause
from .recovery_authority import (
    PROMOTION_OWNED_CONDITIONS,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import Checkpointer

__all__ = ["reconcile_threads_on_startup"]


async def reconcile_threads_on_startup(
    session: AsyncSession,
    checkpointer: Checkpointer,
) -> dict[str, int]:
    """Request bounded checkpoint settlement before any worker demand gate.

    Each run's pause is re-projected BEFORE its checkpoint is reconciled. The
    nudge that would have recorded a pause can be lost with the process that was
    serving the run, which leaves a parked run reading ``running``; checkpoint
    reconciliation reads that as a writer that died and elects ``reconciling``,
    after which the re-dispatch sweep sends the run's accepted work to a worker
    again while a human is still answering its question. Reading the pause off
    the checkpoint first is what stops that: a run that reads ``input_required``
    is explicitly left alone by the election below.
    """
    rows = await list_non_terminal_threads(session)
    thread_ids = [row.id for row in rows]
    await session.commit()
    deadline = (
        asyncio.get_running_loop().time()
        + domain_config.thread_list_checkpoint_deadline_seconds
    )
    settled = paused = unavailable = owned = 0
    for thread_id in thread_ids:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        await reconcile_run_pause(
            session, thread_id=thread_id, checkpointer=checkpointer
        )
        observed = await reconcile_run_checkpoint(
            session,
            checkpointer,
            RecoveryRequest(
                thread_id=thread_id,
                checkpoint_timeout_seconds=remaining,
                trigger=RecoveryTrigger.STARTUP,
            ),
        )
        settled += int(observed.status is ThreadStatus.COMPLETED)
        paused += int(observed.status is ThreadStatus.INPUT_REQUIRED)
        unavailable += int(observed.condition == "checkpoint_unavailable")
        owned += int(observed.condition in PROMOTION_OWNED_CONDITIONS)
    return {
        # A run a promoter is answerable for is not backlog, and neither is one
        # parked on a question: nobody has to look at either, and counting them
        # would make an ordinary multi-turn conversation, or a run waiting on a
        # human over a restart, read as a boot that found damage.
        "repair_backlog": len(thread_ids) - settled - owned - paused,
        "paused_resumable": paused,
        "checkpoint_unavailable": unavailable,
        "owned_by_promotion": owned,
    }
