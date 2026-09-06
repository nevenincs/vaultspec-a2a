"""Startup entry to the shared durable recovery authority."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..control.recovery_authority import RecoveryTrigger, reconcile_run_checkpoint
from ..domain_config import domain_config
from ..thread.enums import ThreadStatus
from .thread_repository import list_non_terminal_threads

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .checkpoints import Checkpointer

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
    settled = paused = unavailable = 0
    for thread_id in thread_ids:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        observed = await reconcile_run_checkpoint(
            session,
            checkpointer,
            thread_id,
            checkpoint_timeout_seconds=remaining,
            trigger=RecoveryTrigger.STARTUP,
        )
        settled += int(observed.status is ThreadStatus.COMPLETED)
        paused += int(observed.status is ThreadStatus.INPUT_REQUIRED)
        unavailable += int(observed.condition == "checkpoint_unavailable")
    return {
        "repair_backlog": len(thread_ids) - settled,
        "paused_resumable": paused,
        "checkpoint_unavailable": unavailable,
    }
