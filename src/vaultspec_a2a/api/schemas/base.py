"""Base envelope model for the progress-stream wire protocol.

``EventEnvelope`` is the base for all thread-scoped server-to-client events.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .enums import ServerEventType

__all__ = [
    "EventEnvelope",
]


class EventEnvelope(BaseModel):
    """Base model for thread-scoped server-to-client progress events.

    Every event carries routing metadata so the frontend can dispatch it
    to the correct thread store without inspecting the payload.
    """

    type: ServerEventType
    thread_id: str
    agent_id: str | None = None
    timestamp: datetime
    sequence: int
    metadata: dict[str, Any] | None = None
