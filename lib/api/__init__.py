"""FastAPI layer for the A2A Orchestrator.

Note: ``create_app``, ``router``, ``get_aggregator``, and
``ConnectionManager`` are intentionally NOT re-exported from this facade.
They depend on ``lib.core.aggregator``, which in turn imports from
``lib.api.schemas``, creating a circular import if exposed here.

Import them directly instead::

    from lib.api.app import create_app
    from lib.api.endpoints import router, get_aggregator
    from lib.api.websocket import ConnectionManager
"""

from .schemas import ClientCommand as ClientCommand
from .schemas import ClientMessage as ClientMessage
from .schemas import EventEnvelope as EventEnvelope
from .schemas import ServerEvent as ServerEvent
from .schemas import ThreadStateSnapshot as ThreadStateSnapshot


__all__ = [
    "ClientCommand",
    "ClientMessage",
    "EventEnvelope",
    "ServerEvent",
    "ThreadStateSnapshot",
]
