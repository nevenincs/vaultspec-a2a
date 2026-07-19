"""WebSocket connection manager and message router.

Implements the multiplexed WebSocket protocol:
- Single WebSocket per client
- Client subscription management (subscribe/unsubscribe per thread)
- Heartbeat every 30 seconds
- ConnectedEvent on open
- Client command dispatch via discriminated union parsing
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from ..control.config import settings
from ..streaming.aggregator import EventAggregator, SequencedEvent
from ..telemetry.instrumentation import get_meter, get_tracer
from ..telemetry.middleware import inject_trace_context, ws_span
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from .event_adapter import sequenced_to_wire
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
from .schemas.events import ConnectedEvent, ErrorEvent, HeartbeatEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OTel instrumentation
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

__all__ = ["ConnectionManager", "WebSocketCommandRejectedError"]

# Type alias for the message handler callback
MessageHandler = Callable[[str, str, str | None], Awaitable[None]]

# Type alias for the agent control handler callback:
# (thread_id, agent_id, action) -> None
AgentControlHandler = Callable[[str, str, AgentControlAction], Awaitable[None]]

_SERVER_VERSION = "0.1.0"

# Mirrors the worker heartbeat ladder's cadence (worker/ipc.py heartbeat_loop):
# every Nth consecutive failure escalates to full WARNING detail again.
_WS_HEARTBEAT_FAILURE_LOG_EVERY_N = 5

_client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class WebSocketCommandRejectedError(Exception):
    """Structured rejection for accepted WebSocket connections."""

    def __init__(
        self,
        *,
        thread_id: str,
        code: str,
        message: str,
        recoverable: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialise a structured rejection payload for websocket clients."""
        super().__init__(message)
        self.thread_id = thread_id
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.metadata = metadata


class ConnectionManager:
    """Manages WebSocket connections and routes messages.

    Each connected client gets a unique ``client_id``, a subscription set,
    and a dedicated event queue from the ``EventAggregator``.
    """

    def __init__(self, aggregator: EventAggregator) -> None:
        """Initialise the manager with the shared EventAggregator."""
        self._aggregator = aggregator
        self._connections: dict[str, WebSocket] = {}
        self._writer_tasks: dict[str, asyncio.Task[None]] = {}
        self._start_time = time.monotonic()
        # Callback for SEND_MESSAGE: (thread_id, content, agent_id) -> None
        self._message_handler: MessageHandler | None = None
        # Callback for AGENT_CONTROL: (thread_id, agent_id, action) -> None
        self._agent_control_handler: AgentControlHandler | None = None
        # Per-connection error sequence counters (sequences start at 1)
        self._error_sequences: dict[str, int] = {}
        # Server-wide heartbeat-send failure ladder (mirrors the worker
        # heartbeat ladder in worker/ipc.py): a single client's writer loop
        # breaks on its own first heartbeat failure (no per-client "consecutive"
        # to track), but many independently-failing clients around the same
        # network blip would otherwise each log identically - this counter is
        # scoped to the manager so that storm dedups instead.
        self._consecutive_heartbeat_failures = 0

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
            # Source active threads from worker heartbeat data, not
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

            # Start the unified writer loop (handles both events and heartbeats).
            #
            # Policy exception: asyncio.create_task() is used here
            # instead of anyio because this task must outlive connect().
            # An anyio.TaskGroup blocks until children complete, which would
            # prevent returning control to the listen() read loop.  The WS
            # lifecycle (connect -> listen -> disconnect) is inherently
            # asyncio-based via Starlette's WebSocket transport.
            wr_task = asyncio.create_task(self._writer_loop(client_id, queue))
            self._writer_tasks[client_id] = wr_task

        logger.info(
            "WebSocket client %s connected",
            client_id,
            extra={"client_id": client_id, "action": "ws_connect"},
        )
        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Clean up a disconnected client."""
        async with ws_span("ws.disconnect", client_id=client_id):
            # Cancel writer task and await it to prevent shutdown race
            writer_task = self._writer_tasks.pop(client_id, None)
            if writer_task is not None:
                writer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await writer_task

            # Remove from aggregator
            self._aggregator.remove_subscriber(client_id)

            # Remove connection and error sequence counter
            self._connections.pop(client_id, None)
            self._error_sequences.pop(client_id, None)

        logger.info(
            "WebSocket client %s disconnected",
            client_id,
            extra={"client_id": client_id, "action": "ws_disconnect"},
        )

    # ------------------------------------------------------------------
    # Message reading loop (run from endpoint handler)
    # ------------------------------------------------------------------

    async def listen(self, client_id: str) -> None:
        """Read and dispatch incoming client commands until disconnect.

        This should be called from the WebSocket endpoint handler.
        Disconnects unresponsive clients after
        ``settings.ws_dead_client_timeout_seconds`` of silence
        (3 missed heartbeats).
        """
        websocket = self._connections.get(client_id)
        if websocket is None:
            return

        try:
            while True:
                try:
                    # Receive as text first to validate size before parsing.
                    # Policy exception: asyncio.wait_for is used here
                    # because Starlette's receive_text() returns an asyncio
                    # coroutine and the anyio equivalent (fail_after) expects
                    # an async callable, not an awaitable.
                    raw_text = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=settings.ws_dead_client_timeout_seconds,
                    )
                except TimeoutError:
                    logger.warning(
                        "Client %s timed out (%.0fs), disconnecting",
                        client_id,
                        settings.ws_dead_client_timeout_seconds,
                        extra={
                            "client_id": client_id,
                            "action": "timeout_disconnect",
                            "timeout_seconds": settings.ws_dead_client_timeout_seconds,
                        },
                    )
                    break
                # Reject oversized messages to prevent memory exhaustion
                msg_bytes = len(raw_text.encode())
                if msg_bytes > settings.ws_max_message_bytes:
                    logger.warning(
                        "Client %s sent oversized message (%d bytes > %d limit)",
                        client_id,
                        msg_bytes,
                        settings.ws_max_message_bytes,
                        extra={
                            "client_id": client_id,
                            "action": "oversized_message",
                            "message_bytes": msg_bytes,
                            "message_bytes_limit": settings.ws_max_message_bytes,
                        },
                    )
                    continue
                try:
                    raw = json.loads(raw_text)
                except (ValueError, TypeError):
                    logger.warning(
                        "Client %s sent non-JSON text message, dropping",
                        client_id,
                        extra={
                            "client_id": client_id,
                            "action": "invalid_json_message",
                        },
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
            extra={
                "client_id": client_id,
                "action": "subscribe",
                "thread_ids": cmd.thread_ids,
                "thread_count": len(cmd.thread_ids),
            },
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
            extra={
                "client_id": client_id,
                "action": "unsubscribe",
                "thread_ids": cmd.thread_ids,
                "thread_count": len(cmd.thread_ids),
            },
        )

    async def _handle_send_message(
        self, client_id: str, cmd: SendMessageCommand
    ) -> None:
        """Handle SEND_MESSAGE command."""
        logger.info(
            "Client %s sent message to thread %s",
            client_id,
            cmd.thread_id,
            extra={
                "client_id": client_id,
                "thread_id": cmd.thread_id,
                "agent_id": cmd.agent_id,
                "action": "send_message",
                "command_type": str(cmd.type.value),
            },
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
                agent_id=cmd.agent_id or DEFAULT_SUPERVISOR_ID,
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
            extra={
                "client_id": client_id,
                "thread_id": cmd.thread_id,
                "agent_id": cmd.agent_id,
                "action": str(cmd.action.value),
                "command_type": str(cmd.type.value),
            },
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
                extra={
                    "client_id": client_id,
                    "thread_id": cmd.thread_id,
                    "agent_id": cmd.agent_id,
                    "action": str(cmd.action.value),
                    "command_type": str(cmd.type.value),
                },
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
            extra={
                "client_id": client_id,
                "thread_id": cmd.request_id.split(":", 1)[0]
                if ":" in cmd.request_id
                else "",
                "request_id": cmd.request_id,
                "action": "permission_response",
                "command_type": str(cmd.type.value),
            },
        )
        # Extract thread_id from request_id ("{thread_id}:{uuid}")
        _req_id = cmd.request_id or ""
        _thread_id = _req_id.split(":", 1)[0] if ":" in _req_id else ""
        await self._send_error_event(
            client_id,
            thread_id=_thread_id,
            code="PERMISSION_RESPONSE_WS_FORBIDDEN",
            message=(
                "Permission responses must be submitted via "
                "REST: POST /api/permissions/{id}/respond"
            ),
            recoverable=True,
        )

    async def _handle_ping(self, client_id: str) -> None:
        """Handle PING command by sending an immediate PONG-style heartbeat."""
        logger.debug(
            "Client %s ping",
            client_id,
            extra={
                "client_id": client_id,
                "action": "ping",
                "command_type": str(ClientCommandType.PING.value),
            },
        )
        websocket = self._connections.get(client_id)
        if websocket is not None and websocket.client_state == WebSocketState.CONNECTED:
            pong = HeartbeatEvent(
                timestamp=datetime.now(UTC),
                server_uptime_seconds=time.monotonic() - self._start_time,
            )
            try:
                await websocket.send_json(pong.model_dump(mode="json"))
            except Exception:
                logger.warning(
                    "Failed to send pong to client %s",
                    client_id,
                    extra={"client_id": client_id, "action": "send_pong"},
                    exc_info=True,
                )

    async def _send_error_event(
        self,
        client_id: str,
        *,
        thread_id: str,
        code: str,
        message: str,
        recoverable: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send a structured error event over an accepted WebSocket."""
        websocket = self._connections.get(client_id)
        if websocket is None:
            return
        try:
            self._error_sequences[client_id] = (
                self._error_sequences.get(client_id, 0) + 1
            )
            error = ErrorEvent(
                thread_id=thread_id,
                agent_id=None,
                code=code,
                message=message,
                recoverable=recoverable,
                timestamp=datetime.now(UTC),
                sequence=self._error_sequences[client_id],
                metadata=metadata,
            )
            await websocket.send_json(error.model_dump(mode="json"))
        except Exception:
            logger.warning(
                "Could not send websocket error %s to client %s",
                code,
                client_id,
                extra={
                    "client_id": client_id,
                    "thread_id": thread_id,
                    "error_code": code,
                    "action": "send_error_event",
                },
            )

    async def _handle_client_message(
        self,
        client_id: str,
        raw: dict[str, Any],
    ) -> None:
        """Parse and dispatch a single client command."""
        try:
            command = _client_message_adapter.validate_python(raw)
        except ValidationError:
            logger.warning(
                "Invalid client command from %s: %s",
                client_id,
                raw,
                extra={
                    "client_id": client_id,
                    "action": "invalid_command",
                    "command_payload": raw,
                },
            )
            return

        async with ws_span(
            "ws.command",
            client_id=client_id,
            command_type=str(command.type.value),
        ):
            try:
                match command.type:
                    case ClientCommandType.SUBSCRIBE:
                        await self._handle_subscribe(client_id, command)
                    case ClientCommandType.UNSUBSCRIBE:
                        await self._handle_unsubscribe(client_id, command)
                    case ClientCommandType.SEND_MESSAGE:
                        await self._handle_send_message(client_id, command)
                    case ClientCommandType.AGENT_CONTROL:
                        await self._handle_agent_control(client_id, command)
                    case ClientCommandType.PERMISSION_RESPONSE:
                        await self._handle_permission_response(client_id, command)
                    case ClientCommandType.PING:
                        await self._handle_ping(client_id)
            except WebSocketCommandRejectedError as exc:
                logger.warning(
                    "Rejected websocket command from %s for thread %s: %s",
                    client_id,
                    exc.thread_id,
                    exc.code,
                    extra={
                        "client_id": client_id,
                        "thread_id": exc.thread_id,
                        "error_code": exc.code,
                        "action": "command_rejected",
                        "recoverable": exc.recoverable,
                    },
                )
                await self._send_error_event(
                    client_id,
                    thread_id=exc.thread_id,
                    code=exc.code,
                    message=exc.message,
                    recoverable=exc.recoverable,
                    metadata=exc.metadata,
                )

    # ------------------------------------------------------------------
    # Writer loop (event queue -> WebSocket)
    # ------------------------------------------------------------------

    def _log_heartbeat_failure(self, client_id: str) -> None:
        """Log a heartbeat-send failure at the same escalation ladder cadence
        as the worker heartbeat loop (worker/ipc.py): full detail on the 1st
        and every Nth consecutive failure across ALL clients, since one
        client's writer loop breaks on its own first failure (nothing
        "consecutive" to track per connection) but many clients failing
        together around the same network blip must not each log identically.
        """
        self._consecutive_heartbeat_failures += 1
        n = self._consecutive_heartbeat_failures
        if n == 1 or n % _WS_HEARTBEAT_FAILURE_LOG_EVERY_N == 0:
            logger.warning(
                "Heartbeat failed for client %s (%d consecutive"
                " heartbeat failures across all clients)",
                client_id,
                n,
                extra={
                    "client_id": client_id,
                    "action": "send_heartbeat",
                    "consecutive_failures": n,
                },
                exc_info=True,
            )

    def _record_heartbeat_success(self) -> None:
        """Reset the heartbeat-failure ladder and note recovery after failures."""
        if self._consecutive_heartbeat_failures > 0:
            logger.info(
                "Heartbeat delivery recovered after %d consecutive failures",
                self._consecutive_heartbeat_failures,
            )
        self._consecutive_heartbeat_failures = 0

    async def _writer_loop(
        self,
        client_id: str,
        queue: asyncio.Queue,
    ) -> None:
        """Drain the event queue and write to the WebSocket.

        Heartbeats are sent inline when the queue is idle for
        ``settings.ws_heartbeat_interval_seconds``, preventing interleaving between
        a separate heartbeat task and the event writer.

        Each outgoing frame is enriched with a ``_trace`` dict containing
        W3C TraceContext (``traceparent`` / ``tracestate``) so that
        downstream consumers can reconstruct the distributed trace.
        """
        websocket = self._connections.get(client_id)
        if websocket is None:
            return

        try:
            while True:
                if websocket.client_state != WebSocketState.CONNECTED:
                    break

                # Wait for the next event or send a heartbeat on timeout.
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=settings.ws_heartbeat_interval_seconds
                    )
                except TimeoutError:
                    # No events for _HEARTBEAT_INTERVAL — send heartbeat.
                    if websocket.client_state != WebSocketState.CONNECTED:
                        break
                    heartbeat = HeartbeatEvent(
                        timestamp=datetime.now(UTC),
                        server_uptime_seconds=time.monotonic() - self._start_time,
                    )
                    try:
                        await websocket.send_json(heartbeat.model_dump(mode="json"))
                        _ws_heartbeats_counter.add(1, {"client_id": client_id})
                        self._record_heartbeat_success()
                    except Exception:
                        self._log_heartbeat_failure(client_id)
                        break
                    continue

                try:
                    wire_event = (
                        sequenced_to_wire(event)
                        if isinstance(event, SequencedEvent)
                        else event
                    )
                    payload = (
                        wire_event.model_dump(mode="json")
                        if hasattr(wire_event, "model_dump")
                        else wire_event
                    )
                    # Inject trace context into WS frames
                    trace_carrier: dict[str, str] = {}
                    inject_trace_context(trace_carrier)
                    if trace_carrier:
                        payload["_trace"] = trace_carrier
                    await websocket.send_json(payload)
                    _ws_events_sent_counter.add(1, {"client_id": client_id})
                except Exception:
                    _ws_send_failures_counter.add(1, {"client_id": client_id})
                    logger.warning(
                        "Failed to send event to client %s",
                        client_id,
                        extra={"client_id": client_id, "action": "send_event"},
                    )
                    break
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Direct broadcast (internal relay path)
    # ------------------------------------------------------------------

    async def broadcast_to_thread(
        self, thread_id: str, payload: dict[str, Any]
    ) -> None:
        """Enqueue a pre-serialised event dict for all subscribers.

        Routes to all clients subscribed to *thread_id*.

        Used by the internal WebSocket relay (``vaultspec_a2a.api.internal``) to forward
        worker events to browser clients.  Events are routed through per-client
        queues so a slow client cannot stall the relay for others.
        Drop-oldest backpressure is applied when a client queue is full.

        Clients without a registered queue are silently skipped.
        """
        for client_id in list(self._connections):
            client_subs = self._aggregator.get_subscriptions(client_id)
            if thread_id not in client_subs:
                continue
            queue = self._aggregator.get_subscriber_queue(client_id)
            if queue is None:
                continue
            if queue.full():
                try:
                    queue.get_nowait()
                    logger.warning(
                        "Dropped oldest event for slow client %s "
                        "(relay backpressure, maxsize=%d)",
                        client_id,
                        queue.maxsize,
                        extra={
                            "client_id": client_id,
                            "thread_id": thread_id,
                            "action": "relay_drop_oldest",
                            "queue_maxsize": queue.maxsize,
                        },
                    )
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(cast("SequencedEvent", payload))
            except asyncio.QueueFull:
                logger.warning(
                    "Relay event dropped for client %s — queue still full",
                    client_id,
                    extra={
                        "client_id": client_id,
                        "thread_id": thread_id,
                        "action": "relay_drop_event",
                        "queue_maxsize": queue.maxsize,
                    },
                )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Disconnect all clients and clean up."""
        client_ids = list(self._connections.keys())
        for client_id in client_ids:
            await self.disconnect(client_id)
