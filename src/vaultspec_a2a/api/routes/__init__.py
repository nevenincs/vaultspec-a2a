"""Route modules for the A2A gateway.

Two routers, mounted by ``register_routes``: the versioned product surface under
``/v1``, and administrative shutdown at the root.
"""

from fastapi import FastAPI

from .admin import router as admin_router
from .gateway import router as gateway_router

__all__ = ["register_routes"]


def register_routes(app: FastAPI) -> None:
    """Include the gateway's routers.

    The versioned ``/v1`` surface is the whole product surface; it carries its
    own prefix and attach gate. Administrative shutdown is a lifecycle operation
    on the process rather than a product capability, so it mounts at the root
    and carries its own double gate - attach plus the receipt-bound lifecycle
    capability - declared on the route itself.
    """
    app.include_router(admin_router)
    app.include_router(gateway_router)
