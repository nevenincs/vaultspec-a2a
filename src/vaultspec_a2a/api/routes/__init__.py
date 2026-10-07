"""Route modules for the A2A gateway.

Two routers, mounted by ``register_routes``: the versioned product surface under
``/v1``, and administrative shutdown at the root.
"""

from fastapi import FastAPI

from ._gateway_action_endpoints import register as _register_action_endpoints
from ._gateway_action_endpoints import route_signature
from ._gateway_read_endpoints import register as _register_read_endpoints
from ._gateway_run_start import register as _register_run_start
from .admin import router as admin_router
from .gateway import router as gateway_router

__all__ = ["register_routes", "route_signature"]

# The verbs mount once per process: the router is a module-level singleton that
# every app includes, so a mount per ``register_routes`` call would duplicate
# each route.
_register_run_start(gateway_router)
_register_read_endpoints(gateway_router)
_register_action_endpoints(gateway_router)


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
