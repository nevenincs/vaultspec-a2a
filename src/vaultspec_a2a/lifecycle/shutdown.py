"""One absolute deadline for an owned server's complete shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import uvicorn

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from fastapi import FastAPI

__all__ = ["ShutdownDeadline", "ShutdownServer", "finish_before"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShutdownDeadline:
    """A monotonic deadline shared by every phase of one shutdown."""

    expires_at: float

    @classmethod
    def start(cls, total_seconds: float) -> ShutdownDeadline:
        loop = asyncio.get_running_loop()
        return cls(loop.time() + max(total_seconds, 0.0))

    def remaining(self, *, reserve: float = 0.0) -> float:
        return max(self.expires_at - asyncio.get_running_loop().time() - reserve, 0.0)


async def finish_before[T](
    operation: Awaitable[T],
    deadline: ShutdownDeadline,
    *,
    phase: str,
    reserve: float = 0.0,
) -> tuple[bool, T | None]:
    """Run one cleanup phase inside the remaining shared budget.

    ``reserve`` leaves time for a later forced escalation. A phase that overruns
    is cancelled and reported; the caller continues to the next owner while the
    same absolute clock keeps running.
    """
    budget = deadline.remaining(reserve=reserve)
    if budget <= 0:
        if asyncio.isfuture(operation):
            operation.cancel()
        elif inspect.iscoroutine(operation):
            operation.close()
        logger.error("Skipping shutdown phase %s: shared deadline exhausted", phase)
        return False, None
    task = asyncio.ensure_future(operation)
    done, _ = await asyncio.wait({task}, timeout=budget)
    if task in done:
        try:
            return True, task.result()
        except asyncio.CancelledError:
            return False, None
        except Exception:
            logger.exception("Shutdown phase %s failed", phase)
            return False, None
    task.cancel()
    await asyncio.sleep(0)
    if task.done():
        _consume_result(task)
    else:
        task.add_done_callback(_consume_result)
    logger.error("Shutdown phase %s exceeded the shared deadline", phase)
    return False, None


def _consume_result[T](task: asyncio.Future[T]) -> None:
    """Retrieve a detached cancelled phase's outcome to avoid orphan warnings."""
    with contextlib.suppress(BaseException):
        task.result()


class ShutdownServer(uvicorn.Server):
    """Uvicorn server that publishes the shutdown clock to its ASGI app.

    Uvicorn drains open HTTP requests before it enters the application lifespan.
    Starting the clock in :meth:`shutdown` lets the lifespan consume only what
    remains after that connection drain instead of silently starting a second
    timeout.
    """

    def __init__(self, config: uvicorn.Config, *, app: FastAPI, total_seconds: float):
        super().__init__(config)
        self._app = app
        self._total_seconds = total_seconds

    async def shutdown(self, sockets: list | None = None) -> None:
        if getattr(self._app.state, "shutdown_deadline", None) is None:
            self._app.state.shutdown_deadline = ShutdownDeadline.start(
                self._total_seconds
            )
        await super().shutdown(sockets=sockets)
