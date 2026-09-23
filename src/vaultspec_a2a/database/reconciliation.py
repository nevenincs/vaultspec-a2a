"""Startup entry to the shared durable recovery authority."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..control.recovery_authority import (
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from ..domain_config import domain_config
from ..thread.enums import ThreadStatus
from .permission_repository import prune_repair_journal
from .session import begin_write_transaction
from .thread_repository import list_non_terminal_threads

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .checkpoints import Checkpointer

__all__ = ["reconcile_threads_on_startup"]

_REPAIR_ROWS_PER_BOOT = 2
"""Each boot appends one ``repair_started``/``repair_finished`` pair per thread."""


async def reconcile_threads_on_startup(
    session: AsyncSession,
    checkpointer: Checkpointer,
    *,
    retain_repair_boots: int = 0,
) -> dict[str, int]:
    """Request bounded checkpoint settlement before any worker demand gate.

    ``retain_repair_boots`` bounds the startup-repair journal to its newest N
    boots' worth of ``repair_started``/``repair_finished`` pairs, once settled.
    Zero (the default) disables pruning, preserving unbounded journal growth.
    """
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
            RecoveryRequest(
                thread_id=thread_id,
                checkpoint_timeout_seconds=remaining,
                trigger=RecoveryTrigger.STARTUP,
            ),
        )
        settled += int(observed.status is ThreadStatus.COMPLETED)
        paused += int(observed.status is ThreadStatus.INPUT_REQUIRED)
        unavailable += int(observed.condition == "checkpoint_unavailable")
    if retain_repair_boots > 0 and thread_ids:
        # The settlement loop above leaves whatever transaction it last opened;
        # the prune reads before it deletes, so it takes a fresh one that holds
        # the write lock from its first statement.
        await session.commit()
        await begin_write_transaction(session)
        await prune_repair_journal(
            session,
            thread_ids=thread_ids,
            keep_rows=retain_repair_boots * _REPAIR_ROWS_PER_BOOT,
        )
    return {
        "repair_backlog": len(thread_ids) - settled,
        "paused_resumable": paused,
        "checkpoint_unavailable": unavailable,
    }
