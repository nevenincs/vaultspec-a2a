"""Per-resource route modules for the A2A gateway REST API.

Each sub-module defines its own ``APIRouter``. The ``register_routes``
helper includes them all under the ``/api`` prefix.
"""

from fastapi import FastAPI

from .admin import router as admin_router
from .cancel import router as cancel_router
from .health import router as health_router
from .messages import router as messages_router
from .permissions import router as permissions_router
from .teams import router as teams_router
from .thread_state import router as thread_state_router
from .thread_stream import router as thread_stream_router
from .threads import router as threads_router

__all__ = ["register_routes"]


def register_routes(app: FastAPI) -> None:
    """Include all per-resource routers under ``/api``."""
    for sub_router in (
        health_router,
        threads_router,
        thread_stream_router,
        thread_state_router,
        messages_router,
        cancel_router,
        teams_router,
        permissions_router,
        admin_router,
    ):
        app.include_router(sub_router, prefix="/api")
