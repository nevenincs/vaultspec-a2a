"""Join owned cleanup before propagating caller cancellation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable


async def complete_cleanup[T](operation: Awaitable[T]) -> T:
    """Finish a bounded release even when the caller is cancelled repeatedly.

    The operation owns its deadlines. Keeping and joining its task is essential:
    shielding alone lets the caller discard resources while release still runs.
    Cancellation is delayed, never absorbed; an operation failure remains its
    cause when both occur.
    """
    pending = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            if pending.cancelled():
                raise
            cancellation = exc
        except Exception:
            break

    try:
        result = pending.result()
    except BaseException as exc:
        if cancellation is not None:
            raise cancellation from exc
        raise
    if cancellation is not None:
        raise cancellation
    return result
