"""Per-resource route modules for the A2A gateway REST API.

Each sub-module defines its own ``APIRouter``. The ``register_routes``
helper includes them all under the ``/api`` prefix.
"""

from fastapi import Depends, FastAPI

from ..dependencies import require_attach
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
    replay) is the dashboard product surface: every product router carries the
    attach-control gate, so an unauthenticated local client can no longer reach
    it. The aggregate readiness probe stays ungated as the minimal liveness
    surface. The versioned ``/v1`` surface is the engine-facing edge and carries
    its own ``/v1`` prefix and attach gate.
    """
    # Minimal liveness is ungated: the readiness probe proves neither ownership
    # nor product state and must answer an unauthenticated caller.
    app.include_router(health_router, prefix="/api")

    for sub_router in (
        threads_router,
        thread_stream_router,
        thread_state_router,
        messages_router,
        cancel_router,
        teams_router,
        permissions_router,
        admin_router,
    ):
        app.include_router(
            sub_router, prefix="/api", dependencies=[Depends(require_attach)]
        )

    # The v1 gateway is the versioned engine edge.
    app.include_router(gateway_router)
