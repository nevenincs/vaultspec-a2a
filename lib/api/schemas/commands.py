"""Client-to-server WebSocket command models.

Each command uses a ``Literal`` type discriminator for the top-level
``ClientMessage`` union.
"""

from typing import Annotated, Literal

from pydantic import Field

from .base import ClientCommand
from .enums import AgentControlAction, ClientCommandType


__all__ = [
    "AgentControlCommand",
    "ClientMessage",
    "PermissionResponseCommand",
    "PingCommand",
    "SendMessageCommand",
    "SubscribeCommand",
    "UnsubscribeCommand",
]


class SubscribeCommand(ClientCommand):
    """Subscribe to real-time events for one or more threads.

    M15: thread_ids are validated as exact IDs (max 50 per command) to
    prevent subscription abuse. IDs are treated as opaque strings — the
    aggregator uses exact-match comparison, never prefix matching.
    """

    type: Literal[ClientCommandType.SUBSCRIBE] = ClientCommandType.SUBSCRIBE
    # max_length=50 prevents a single command from subscribing to an
    # unreasonably large number of threads at once.
    thread_ids: list[str] = Field(max_length=50)


class UnsubscribeCommand(ClientCommand):
    """Unsubscribe from real-time events for one or more threads."""

    type: Literal[ClientCommandType.UNSUBSCRIBE] = ClientCommandType.UNSUBSCRIBE
    thread_ids: list[str] = Field(max_length=50)


class SendMessageCommand(ClientCommand):
    """Send a user message into a thread."""

    type: Literal[ClientCommandType.SEND_MESSAGE] = ClientCommandType.SEND_MESSAGE
    thread_id: str
    # 64 KB limit prevents memory exhaustion and excessive LLM token consumption
    content: str = Field(max_length=65536)
    agent_id: str | None = None


class AgentControlCommand(ClientCommand):
    """Issue a control action (pause/resume/terminate) to an agent."""

    type: Literal[ClientCommandType.AGENT_CONTROL] = ClientCommandType.AGENT_CONTROL
    thread_id: str
    agent_id: str
    action: AgentControlAction
    option_id: str | None = None


class PermissionResponseCommand(ClientCommand):
    """Respond to a permission request via WebSocket."""

    type: Literal[ClientCommandType.PERMISSION_RESPONSE] = (
        ClientCommandType.PERMISSION_RESPONSE
    )
    request_id: str
    option_id: str


class PingCommand(ClientCommand):
    """Client keepalive ping."""

    type: Literal[ClientCommandType.PING] = ClientCommandType.PING


ClientMessage = Annotated[
    SubscribeCommand
    | UnsubscribeCommand
    | SendMessageCommand
    | AgentControlCommand
    | PermissionResponseCommand
    | PingCommand,
    Field(discriminator="type"),
]
