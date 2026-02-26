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
    """Subscribe to real-time events for one or more threads."""

    type: Literal[ClientCommandType.SUBSCRIBE] = ClientCommandType.SUBSCRIBE
    thread_ids: list[str]


class UnsubscribeCommand(ClientCommand):
    """Unsubscribe from real-time events for one or more threads."""

    type: Literal[ClientCommandType.UNSUBSCRIBE] = ClientCommandType.UNSUBSCRIBE
    thread_ids: list[str]


class SendMessageCommand(ClientCommand):
    """Send a user message into a thread."""

    type: Literal[ClientCommandType.SEND_MESSAGE] = ClientCommandType.SEND_MESSAGE
    thread_id: str
    content: str
    agent_id: str | None = None


class AgentControlCommand(ClientCommand):
    """Issue a control action (pause/resume/terminate) to an agent."""

    type: Literal[ClientCommandType.AGENT_CONTROL] = ClientCommandType.AGENT_CONTROL
    thread_id: str
    agent_id: str
    action: AgentControlAction


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
