"""POST /admin/shutdown -- Graceful shutdown (BE-G)."""

import asyncio
import os
import signal

from fastapi import APIRouter, Depends, Request

from ..dependencies import require_attach, require_lifecycle_capability
from .gateway import admission_gate

router = APIRouter()

# Brief delay before the in-process stop so this 202 response flushes to the
# caller before the SIGINT-driven graceful shutdown tears the listener down.
_STOP_DELAY_SECONDS = 0.25


def _stop_this_process() -> None:
    """Send this process the graceful-shutdown signal."""
    os.kill(os.getpid(), signal.SIGINT)


@router.post(
    "/admin/shutdown",
    status_code=202,
    dependencies=[
        Depends(require_attach),
        Depends(require_lifecycle_capability),
    ],
)
async def shutdown_endpoint(request: Request) -> dict[str, str]:
    """Initiate graceful server shutdown.

    Administrative shutdown is a receipt-bound lifecycle operation: it requires
    both authenticated runtime control (the attach credential) and receipt
    ownership (the lifecycle capability that discovery never references), so a
    foreign attachment that can reach the product surface still cannot stop the
    gateway.

    Run admission is closed first, so the gateway admits no new run while it
    drains; the in-process stop is then deferred briefly so this 202 flushes
    before the SIGINT-driven graceful shutdown - which drains and reaps the owned
    worker and run descendants in the lifespan - begins.
    """
    await admission_gate(request.app).close_admission()
    asyncio.get_running_loop().call_later(_STOP_DELAY_SECONDS, _stop_this_process)
    return {"status": "shutting_down"}
