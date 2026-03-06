"""WebSocket connection manager and message router.

Implements the multiplexed WebSocket protocol from ADR-004 and ADR-011:
- Single WebSocket per client
- Client subscription management (subscribe/unsubscribe per thread)
- Heartbeat every 30 seconds
- ConnectedEvent on open
- Client command dispatch via discriminated union parsing
"""

import asyncio
import json
import logging
import time

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from ..core import EventAggregator
from ..telemetry.instrumentation import get_meter, get_tracer
from ..telemetry.middleware import inject_trace_context, ws_span
from .schemas.commands import (
    AgentControlCommand,
    ClientMessage,
    PermissionResponseCommand,
    SendMessageCommand,
    SubscribeCommand,
    UnsubscribeCommand,
)
from .schemas.enums import (
    AgentControlAction,
    AgentLifecycleState,
    ClientCommandType,
)
from .schemas.events import ConnectedEvent, ErrorEvent, HeartbeatEvent, ServerEvent


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

# Type alias for the agent control handler callback:
# (thread_id, agent_id, action) -> None
AgentControlHandler = Callable[[str, str, AgentControlAction], Awaitable[None]]

# ADR-011 §5: heartbeat every 30 seconds
_HEARTBEAT_INTERVAL = 30.0

# ADR-011 §5: disconnect unresponsive clients after 90 seconds (3 missed heartbeats)
_DEAD_CLIENT_TIMEOUT = 90.0

# M14: maximum incoming WebSocket frame size (bytes) — reject oversized messages
# to prevent memory exhaustion from malicious or buggy clients.
_MAX_WS_MESSAGE_BYTES = 1 * 1024 * 1024  # 1 MiB

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
        # Callback for AGENT_CONTROL: (thread_id, agent_id, action) -> None
        self._agent_control_handler: AgentControlHandler | None = None
        # Per-connection error sequence counters (API-H2: sequences start at 1)
        self._error_sequences: dict[str, int] = {}

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Register a callback for SEND_MESSAGE commands.

        The handler receives ``(thread_id, content, agent_id)`` and should
        kick off graph execution asynchronously.
        """
        self._message_handler = handler

    def set_agent_control_handler(self, handler: AgentControlHandler) -> None:
        """Register a callback for AGENT_CONTROL commands.

        The handler receives ``(thread_id, agent_id, action)`` and should
        perform the requested control action (terminate, resume, or pause).
        """
        self._agent_control_handler = handler

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
            self._error_sequences[client_id] = 0

            # Register with the aggregator
            queue = self._aggregator.add_subscriber(client_id)

            # Send ConnectedEvent
            # BE-35: source active threads from worker heartbeat data, not
            # WS subscriber list (which is empty on reconnect).  Fall back
            # to aggregator subscriber list if heartbeat hasn't arrived yet.
            worker_threads: list[str] = getattr(
                websocket.app.state, "worker_active_threads", []
            )
            active = (
                sorted(set(worker_threads))
                if worker_threads
                else self._aggregator.get_active_thread_ids()
            )
            connected = ConnectedEvent(
                client_id=client_id,
                server_version=_SERVER_VERSION,
                active_threads=active,
            )
            await websocket.send_json(connected.model_dump(mode="json"))

            # Start heartbeat and writer tasks.
            # H10: cross-cancel so a crash in either task cleans up both.
            # When the writer dies (e.g. broken pipe) the heartbeat should
            # stop too, and vice versa.
            #
            # Policy exception (API-H3): asyncio.create_task() is used here
            # instead of anyio because these tasks must outlive connect().
            # An anyio.TaskGroup blocks until children complete, which would
            # prevent returning control to the listen() read loop.  The WS
            # lifecycle (connect → listen → disconnect) is inherently
            # asyncio-based via Starlette's WebSocket transport.
            hb_task = asyncio.create_task(self._heartbeat_loop(client_id))
            wr_task = asyncio.create_task(self._writer_loop(client_id, queue))

            def _cancel_partner(
                done_task: asyncio.Task,
                other_task: asyncio.Task,
            ) -> None:
                if not other_task.done():
                    other_task.cancel()

            hb_task.add_done_callback(lambda t: _cancel_partner(t, wr_task))
            wr_task.add_done_callback(lambda t: _cancel_partner(t, hb_task))

            self._heartbeat_tasks[client_id] = hb_task
            self._writer_tasks[client_id] = wr_task

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

            # Remove connection and error sequence counter
            self._connections.pop(client_id, None)
            self._error_sequences.pop(client_id, None)

        logger.info("WebSocket client %s disconnected", client_id)

    # ------------------------------------------------------------------
    # Message reading loop (run from endpoint handler)
    # ------------------------------------------------------------------

    async def listen(self, client_id: str) -> None:
        """Read and dispatch incoming client commands until disconnect.

        This should be called from the WebSocket endpoint handler.
        Disconnects unresponsive clients after 90 seconds of silence
        (ADR-011 §5: 3 missed heartbeats).
        """
        websocket = self._connections.get(client_id)
        if websocket is None:
            return

        try:
            while True:
                try:
                    # M14: receive as text first to validate size before parsing.
                    # Policy exception (API-H4): asyncio.wait_for is used here
                    # because Starlette's receive_text() returns an asyncio
                    # coroutine and the anyio equivalent (fail_after) expects
                    # an async callable, not an awaitable.
                    raw_text = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=_DEAD_CLIENT_TIMEOUT,
                    )
                except TimeoutError:
                    logger.warning(
                        "Client %s timed out (%.0fs), disconnecting",
                        client_id,
                        _DEAD_CLIENT_TIMEOUT,
                    )
                    break
                # M14: reject oversized messages to prevent memory exhaustion
                msg_bytes = len(raw_text.encode())
                if msg_bytes > _MAX_WS_MESSAGE_BYTES:
                    logger.warning(
                        "Client %s sent oversized message (%d bytes > %d limit)",
                        client_id,
                        msg_bytes,
                        _MAX_WS_MESSAGE_BYTES,
                    )
                    continue
                try:
                    raw = json.loads(raw_text)
                except (ValueError, TypeError):
                    logger.warning(
                        "Client %s sent non-JSON text message, dropping", client_id
                    )
                    continue
                await self._handle_client_message(client_id, raw)
        except WebSocketDisconnect:
            pass
        finally:
            await self.disconnect(client_id)

    # ------------------------------------------------------------------
    # Client command dispatch
    # ------------------------------------------------------------------

    async def _handle_subscribe(self, client_id: str, cmd: SubscribeCommand) -> None:
        """Handle SUBSCRIBE command."""
        self._aggregator.subscribe(client_id, cmd.thread_ids)
        logger.debug(
            "Client %s subscribed to threads: %s",
            client_id,
            cmd.thread_ids,
        )

    async def _handle_unsubscribe(
        self, client_id: str, cmd: UnsubscribeCommand
    ) -> None:
        """Handle UNSUBSCRIBE command."""
        self._aggregator.unsubscribe(client_id, cmd.thread_ids)
        logger.debug(
            "Client %s unsubscribed from threads: %s",
            client_id,
            cmd.thread_ids,
        )

    async def _handle_send_message(
        self, client_id: str, cmd: SendMessageCommand
    ) -> None:
        """Handle SEND_MESSAGE command."""
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
            # Emit agent status so the frontend knows the message was
            # received even if no graph is wired yet.
            await self._aggregator.emit_agent_status(
                thread_id=cmd.thread_id,
                agent_id=cmd.agent_id or "vaultspec-supervisor",
                node_name="supervisor",
                state=AgentLifecycleState.SUBMITTED,
                detail="Message received, awaiting graph integration",
            )

    async def _handle_agent_control(
        self, client_id: str, cmd: AgentControlCommand
    ) -> None:
        """Handle AGENT_CONTROL command."""
        logger.info(
            "Client %s control action %s on agent %s (thread %s)",
            client_id,
            cmd.action,
            cmd.agent_id,
            cmd.thread_id,
        )
        if self._agent_control_handler is not None:
            await self._agent_control_handler(
                cmd.thread_id,
                cmd.agent_id,
                cmd.action,
            )
        else:
            logger.warning(
                "No agent control handler registered — ignoring %s for thread %s",
                cmd.action,
                cmd.thread_id,
            )

    async def _handle_permission_response(
        self, client_id: str, cmd: PermissionResponseCommand
    ) -> None:
        """Handle PERMISSION_RESPONSE command (REST-only, reject over WS)."""
        logger.warning(
            "Client %s sent permission_response over WebSocket "
            "(request=%s) — rejecting; use REST endpoint",
            client_id,
            cmd.request_id,
        )
        # Extract thread_id from request_id ("{thread_id}:{uuid}")
        _req_id = cmd.request_id or ""
        _thread_id = _req_id.split(":", 1)[0] if ":" in _req_id else ""
        websocket = self._connections.get(client_id)
        if websocket is not None:
            try:
                # API-H2: use a connection-scoped counter so sequences start at 1
                self._error_sequences[client_id] = (
                    self._error_sequences.get(client_id, 0) + 1
                )
                error = ErrorEvent(
                    thread_id=_thread_id,
                    agent_id=None,
                    code="PERMISSION_RESPONSE_WS_FORBIDDEN",
                    message=(
                        "Permission responses must be submitted via "
                        "REST: POST /api/permissions/{id}/respond"
                    ),
                    recoverable=True,
                    timestamp=datetime.now(UTC),
                    sequence=self._error_sequences[client_id],
                )
                await websocket.send_json(error.model_dump(mode="json"))
            except Exception:
                logger.warning(
                    "Could not send permission_response rejection to client %s",
                    client_id,
                )

    async def _handle_ping(self, client_id: str) -> None:
        """Handle PING command by sending an immediate PONG-style heartbeat."""
        logger.debug("Client %s ping", client_id)
        websocket = self._connections.get(client_id)
        if websocket is not None and websocket.client_state == WebSocketState.CONNECTED:
            pong = HeartbeatEvent(
                timestamp=datetime.now(UTC),
                server_uptime_seconds=time.monotonic() - self._start_time,
            )
            try:
                await websocket.send_json(pong.model_dump(mode="json"))
            except Exception:
                logger.warning("Failed to send pong to client %s", client_id)

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
                    await self._handle_subscribe(
                        client_id, cast(SubscribeCommand, command)
                    )
                case ClientCommandType.UNSUBSCRIBE:
                    await self._handle_unsubscribe(
                        client_id, cast(UnsubscribeCommand, command)
                    )
                case ClientCommandType.SEND_MESSAGE:
                    await self._handle_send_message(
                        client_id, cast(SendMessageCommand, command)
                    )
                case ClientCommandType.AGENT_CONTROL:
                    await self._handle_agent_control(
                        client_id, cast(AgentControlCommand, command)
                    )
                case ClientCommandType.PERMISSION_RESPONSE:
                    await self._handle_permission_response(
                        client_id, cast(PermissionResponseCommand, command)
                    )
                case ClientCommandType.PING:
                    await self._handle_ping(client_id)

    # ------------------------------------------------------------------
    # Writer loop (event queue -> WebSocket)
    # ------------------------------------------------------------------

    async def _writer_loop(
        self,
        client_id: str,
        queue: asyncio.Queue[ServerEvent],
    ) -> None:
        """Drain the event queue and write to the WebSocket.

        Each outgoing frame is enriched with a ``_trace`` dict containing
        W3C TraceContext (``traceparent`` / ``tracestate``) so that
        downstream consumers can reconstruct the distributed trace
        (ADR-010 §5).
        """
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
                    # ADR-010 §5: inject trace context into WS frames
                    trace_carrier: dict[str, str] = {}
                    inject_trace_context(trace_carrier)
                    if trace_carrier:
                        payload["_trace"] = trace_carrier
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
    # Direct broadcast (internal relay path — ADR-019)
    # ------------------------------------------------------------------

    async def broadcast_to_thread(
        self, thread_id: str, payload: dict[str, Any]
    ) -> None:
        """Send a pre-serialised event dict to all clients subscribed to *thread_id*.

        Used by the internal WebSocket relay (``vaultspec_a2a.api.internal``) to forward
        worker events to browser clients without round-tripping through the
        ``EventAggregator`` queue machinery.  The payload is a plain ``dict``
        (already JSON-serialisable) produced by the worker's event pipeline.

        Clients whose WebSocket is no longer connected are silently skipped.
        """
        for client_id, websocket in list(self._connections.items()):
            client_subs = self._aggregator.get_subscriptions(client_id)
            if thread_id not in client_subs:
                continue
            if websocket.client_state != WebSocketState.CONNECTED:
                continue
            try:
                await websocket.send_json(payload)
                _ws_events_sent_counter.add(
                    1, {"client_id": client_id, "relay": "internal"}
                )
            except Exception:
                _ws_send_failures_counter.add(
                    1, {"client_id": client_id, "relay": "internal"}
                )
                logger.warning(
                    "Failed to relay event to client %s for thread %s",
                    client_id,
                    thread_id,
                )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Disconnect all clients and clean up."""
        client_ids = list(self._connections.keys())
        for client_id in client_ids:
            await self.disconnect(client_id)
