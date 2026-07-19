"""POST /admin/shutdown -- Graceful shutdown (BE-G)."""

from fastapi import APIRouter, Depends

from ..dependencies import require_attach, require_lifecycle_capability

router = APIRouter()


@router.post(
    "/admin/shutdown",
    status_code=202,
    dependencies=[
        Depends(require_attach),
        Depends(require_lifecycle_capability),
    ],
)
async def shutdown_endpoint() -> dict[str, str]:
    """Initiate graceful server shutdown.

    Administrative shutdown is a receipt-bound lifecycle operation: it requires
    both authenticated runtime control (the attach credential) and receipt
    ownership (the lifecycle capability that discovery never references), so a
    foreign attachment that can reach the product surface still cannot stop the
    gateway.
    """
    import os
    import signal

    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting_down"}
