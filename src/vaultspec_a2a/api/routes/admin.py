"""POST /admin/shutdown -- Graceful shutdown (BE-G)."""

from fastapi import APIRouter

router = APIRouter()


@router.post("/admin/shutdown", status_code=202)
async def shutdown_endpoint() -> dict[str, str]:
    """Initiate graceful server shutdown."""
    import os
    import signal

    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting_down"}
