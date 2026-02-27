"""WebSocket connection manager and message router.

Implements the multiplexed WebSocket protocol from ADR-004 and ADR-011:
- Single WebSocket per client
- Client subscription management (subscribe/unsubscribe per thread)
- Heartbeat every 30 seconds
- ConnectedEvent on open
- Client command dispatch via discriminated union parsing
"""

import asyncio
import logging
import time

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from ..api.schemas.commands import (
    AgentControlCommand,
    ClientMessage,
    PermissionResponseCommand,
    SendMessageCommand,
    SubscribeCommand,
    UnsubscribeCommand,
)
from ..api.schemas.enums import AgentLifecycleState, ClientCommandType
from ..api.schemas.events import ConnectedEvent, HeartbeatEvent, ServerEvent
from ..core.aggregator import EventAggregator
from ..telemetry.instrumentation import get_meter, get_tracer
from ..telemetry.middleware import ws_span


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OTel instrumentation (ADR-010)
# ---------------------------------------------------------------------------
_tracer = get_tracer(__name__)
_meter = get_meter(__name__)

_ws_events_sent_counter = _meter.create_counter(
    "ws.events_sent",
    description="Number of events successfully sent to WebSocket clients",
)
_ws_send_failures_counter = _meter.create_counter(
    "ws.send_failures",
    description="Number of failed WebSocket event sends",
)
_ws_heartbeats_counter = _meter.create_counter(
    "ws.heartbeats_sent",
    description="Number of heartbeat events sent to WebSocket clients",
)

__all__ = ["ConnectionManager"]

# Type alias for the message handler callback
MessageHandler = Callable[[str, str, str | None], Awaitable[None]]

# ADR-011 §5: heartbeat every 30 seconds
_HEARTBEAT_INTERVAL = 30.0

_SERVER_VERSION = "0.1.0"

_client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class ConnectionManager:
    """Manages WebSocket connections and routes messages.

    Each connected client gets a unique ``client_id``, a subscription set,
    and a dedicated event queue from the ``EventAggregator``.
    """

    def __init__(self, aggregator: EventAggregator) -> None:
        """Initialise the manager with the shared EventAggregator."""
        self._aggregator = aggregator
        self._connections: dict[str, WebSocket] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}
        self._writer_tasks: dict[str, asyncio.Task[None]] = {}
        self._start_time = time.monotonic()
        # Callback for SEND_MESSAGE: (thread_id, content, agent_id) -> None
        self._message_handler: MessageHandler | None = None

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Register a callback for SEND_MESSAGE commands.

        The handler receives ``(thread_id, content, agent_id)`` and should
        kick off graph execution asynchronously.
        """
        self._message_handler = handler

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a WebSocket connection and send the ConnectedEvent.

        Returns the assigned ``client_id``.
        """
        await websocket.accept()
        client_id = str(uuid4())

        async with ws_span("ws.connect", client_id=client_id):
            self._connections[client_id] = websocket

            # Register with the aggregator
            queue = self._aggregator.add_subscriber(client_id)

            # Send ConnectedEvent
            connected = ConnectedEvent(
                client_id=client_id,
                server_version=_SERVER_VERSION,
                active_threads=self._aggregator.get_active_thread_ids(),
            )
            await websocket.send_json(connected.model_dump(mode="json"))

            # Start heartbeat and writer tasks
            self._heartbeat_tasks[client_id] = asyncio.create_task(
                self._heartbeat_loop(client_id)
            )
            self._writer_tasks[client_id] = asyncio.create_task(
                self._writer_loop(client_id, queue)
            )

        logger.info("WebSocket client %s connected", client_id)
        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Clean up a disconnected client."""
        async with ws_span("ws.disconnect", client_id=client_id):
            # Cancel heartbeat task
            heartbeat_task = self._heartbeat_tasks.pop(client_id, None)
            if heartbeat_task is not None:
                heartbeat_task.cancel()

            # Cancel writer task
            writer_task = self._writer_tasks.pop(client_id, None)
            if writer_task is not None:
                writer_task.cancel()

            # Remove from aggregator
            self._aggregator.remove_subscriber(client_id)

            # Remove connection
            self._connections.pop(client_id, None)

        logger.info("WebSocket client %s disconnected", client_id)

    # ------------------------------------------------------------------
    # Message reading loop (run from endpoint handler)
    # ------------------------------------------------------------------

    async def listen(self, client_id: str) -> None:
        """Read and dispatch incoming client commands until disconnect.

        This should be called from the WebSocket endpoint handler.
        """
        websocket = self._connections.get(client_id)
        if websocket is None:
            return

        try:
            while True:
                raw = await websocket.receive_json()
                await self._handle_client_message(client_id, raw)
        except WebSocketDisconnect:
            pass
        finally:
            await self.disconnect(client_id)

    # ------------------------------------------------------------------
    # Client command dispatch
    # ------------------------------------------------------------------

    async def _handle_client_message(
        self,
        client_id: str,
        raw: dict[str, Any],
    ) -> None:
        """Parse and dispatch a single client command."""
        try:
            command = _client_message_adapter.validate_python(raw)
        except ValidationError:
            logger.warning("Invalid client command from %s: %s", client_id, raw)
            return

        async with ws_span(
            "ws.command",
            client_id=client_id,
            command_type=str(command.type.value),
        ):
            match command.type:
                case ClientCommandType.SUBSCRIBE:
                    cmd = cast(SubscribeCommand, command)
                    self._aggregator.subscribe(client_id, cmd.thread_ids)
                    logger.debug(
                        "Client %s subscribed to threads: %s",
                        client_id,
                        cmd.thread_ids,
                    )

                case ClientCommandType.UNSUBSCRIBE:
                    cmd = cast(UnsubscribeCommand, command)
                    self._aggregator.unsubscribe(client_id, cmd.thread_ids)
                    logger.debug(
                        "Client %s unsubscribed from threads: %s",
                        client_id,
                        cmd.thread_ids,
                    )

                case ClientCommandType.SEND_MESSAGE:
                    cmd = cast(SendMessageCommand, command)
                    logger.info(
                        "Client %s sent message to thread %s",
                        client_id,
                        cmd.thread_id,
                    )
                    if self._message_handler is not None:
                        await self._message_handler(
                            cmd.thread_id,
                            cmd.content,
                            cmd.agent_id,
                        )
                    else:
                        # Emit agent status so the frontend knows the
                        # message was received even if no graph is wired yet.
                        await self._aggregator.emit_agent_status(
                            thread_id=cmd.thread_id,
                            agent_id=cmd.agent_id or "supervisor",
                            node_name="supervisor",
                            state=AgentLifecycleState.SUBMITTED,
                            detail="Message received, awaiting graph integration",
                        )

                case ClientCommandType.AGENT_CONTROL:
                    cmd = cast(AgentControlCommand, command)
                    logger.info(
                        "Client %s control action %s on agent %s (thread %s)",
                        client_id,
                        cmd.action,
                        cmd.agent_id,
                        cmd.thread_id,
                    )
                    # Agent control will be wired in Task #5

                case ClientCommandType.PERMISSION_RESPONSE:
                    cmd = cast(PermissionResponseCommand, command)
                    logger.info(
                        "Client %s permission response: request=%s option=%s",
                        client_id,
                        cmd.request_id,
                        cmd.option_id,
                    )
                    # Permission responses are preferably handled via REST
                    # (ADR-011 §3.1) for guaranteed delivery

                case ClientCommandType.PING:
                    logger.debug("Client %s ping", client_id)
                    # Pings are acknowledged implicitly by heartbeat

    # ------------------------------------------------------------------
    # Writer loop (event queue -> WebSocket)
    # ------------------------------------------------------------------

    async def _writer_loop(
        self,
        client_id: str,
        queue: asyncio.Queue[ServerEvent],
    ) -> None:
        """Drain the event queue and write to the WebSocket."""
        websocket = self._connections.get(client_id)
        if websocket is None:
            return

        try:
            while True:
                event = await queue.get()
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
                try:
                    payload = (
                        event.model_dump(mode="json")
                        if hasattr(event, "model_dump")
                        else event
                    )
                    await websocket.send_json(payload)
                    _ws_events_sent_counter.add(1, {"client_id": client_id})
                except Exception:
                    _ws_send_failures_counter.add(1, {"client_id": client_id})
                    logger.warning("Failed to send event to client %s", client_id)
                    break
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Heartbeat loop
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self, client_id: str) -> None:
        """Send periodic heartbeat events to keep the connection alive."""
        websocket = self._connections.get(client_id)
        if websocket is None:
            return

        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
                heartbeat = HeartbeatEvent(
                    timestamp=datetime.now(UTC),
                    server_uptime_seconds=time.monotonic() - self._start_time,
                )
                try:
                    await websocket.send_json(heartbeat.model_dump(mode="json"))
                    _ws_heartbeats_counter.add(1, {"client_id": client_id})
                except Exception:
                    logger.warning("Heartbeat failed for client %s", client_id)
                    break
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Disconnect all clients and clean up."""
        client_ids = list(self._connections.keys())
        for client_id in client_ids:
            await self.disconnect(client_id)
