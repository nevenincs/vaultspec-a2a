"""FastAPI layer for the A2A Orchestrator.

Note: ``create_app`` and ``ConnectionManager`` are intentionally NOT
re-exported from this facade.  They depend on
``vaultspec_a2a.core.aggregator``, which in turn imports from
``vaultspec_a2a.api.schemas``, creating a circular import if exposed here.

Import them directly instead::

    from vaultspec_a2a.api.app import create_app
    from vaultspec_a2a.api.dependencies import get_aggregator
    from vaultspec_a2a.api.websocket import ConnectionManager
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
