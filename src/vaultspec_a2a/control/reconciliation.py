"""Startup entry to the shared durable recovery authority."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..database import list_non_terminal_threads
from ..domain_config import domain_config
from ..thread.enums import ThreadStatus
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
    """Request bounded checkpoint settlement before any worker demand gate."""
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
        # A run a promoter is answerable for is not backlog: nobody has to
        # look at it, and counting it would make an ordinary multi-turn
        # conversation read as a boot that found damage.
        "repair_backlog": len(thread_ids) - settled - owned,
        "paused_resumable": paused,
        "checkpoint_unavailable": unavailable,
        "owned_by_promotion": owned,
    }
