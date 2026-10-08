"""The one projection from a live capture to the snapshot a test inspects.

``capture_thread_state`` returns the capture envelope; most tests care only
about the ``ThreadStateSnapshot`` it carries (or ``None`` when the thread
does not exist), so this is the one place that unwraps it rather than every
test module re-deriving the same two-line projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..control.thread_state_service import capture_thread_state

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..streaming import RelayHub
    from ..thread.snapshots import ThreadStateSnapshot

__all__ = ["captured_snapshot"]


async def captured_snapshot(
    session: AsyncSession,
    *,
    thread_id: str,
    relay_hub: RelayHub,
    checkpointer: AsyncSqliteSaver,
) -> ThreadStateSnapshot | None:
    """Project the live capture service to the snapshot a test inspects."""
    capture = await capture_thread_state(
        session,
        thread_id=thread_id,
        relay_hub=relay_hub,
        checkpointer=checkpointer,
    )
    return capture.snapshot if capture is not None else None
