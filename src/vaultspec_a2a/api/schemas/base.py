"""Base envelope models for the WebSocket wire protocol.

``EventEnvelope`` is the base for all thread-scoped server-to-client events.
``ClientCommand`` is the base for all client-to-server commands.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .enums import ClientCommandType, ServerEventType


__all__ = [
    "ClientCommand",
    "EventEnvelope",
]


class EventEnvelope(BaseModel):
    """Base model for thread-scoped server-to-client WebSocket events.

    Every event carries routing metadata so the frontend can dispatch it
    to the correct thread store without inspecting the payload.
    """

    type: ServerEventType
    thread_id: str
    agent_id: str | None = None
    timestamp: datetime
    sequence: int
    metadata: dict[str, Any] | None = None


class ClientCommand(BaseModel):
    """Base model for client-to-server WebSocket commands.

    The ``request_id`` field enables request/response correlation for
    commands that expect an acknowledgement.
    """

    type: ClientCommandType
    request_id: str | None = None
