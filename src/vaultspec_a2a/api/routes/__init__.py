"""Per-resource route modules for the A2A gateway REST API.

Each sub-module defines its own ``APIRouter``. The ``register_routes``
helper includes them all under the ``/api`` prefix.
"""

from fastapi import FastAPI

from .admin import router as admin_router
from .cancel import router as cancel_router
from .gateway import router as gateway_router
from .health import router as health_router
from .messages import router as messages_router
from .permissions import router as permissions_router
from .teams import router as teams_router
from .thread_state import router as thread_state_router
from .thread_stream import router as thread_stream_router
from .threads import router as threads_router

__all__ = ["register_routes"]


def register_routes(app: FastAPI) -> None:
    """Include per-resource routers.

    The internal ``/api`` surface (thread CRUD, permissions, messages, WS
    replay) stays for dashboard-internal and operator use; the versioned
    ``/v1`` five-verb surface is the engine-facing edge and carries
    its own ``/v1`` prefix.
    """
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

    # The five-verb gateway is the versioned engine edge.
    app.include_router(gateway_router)
