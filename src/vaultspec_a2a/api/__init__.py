"""Expose public Hypertext Transfer Protocol and WebSocket API schemas.

API means application programming interface throughout this package.

This package exports the wire types defined by
:mod:`vaultspec_a2a.api.schemas`. It doesn't own application orchestration or
event aggregation.

Build the application with :func:`vaultspec_a2a.api.app.create_app`.
:class:`vaultspec_a2a.api.websocket.ConnectionManager` owns WebSocket
connection state.
:class:`vaultspec_a2a.streaming.aggregator.EventAggregator` owns event
aggregation.

Request handling delegates orchestration to direct
:mod:`vaultspec_a2a.control` service modules. See :doc:`/edge-conformance` for
the edge-to-runtime verb mapping.
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
