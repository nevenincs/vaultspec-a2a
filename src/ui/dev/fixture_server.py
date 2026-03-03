"""Fixture server for visual testing of the React 5 frontend.

Speaks the exact wire protocol expected by src/ui/src/lib/api/ — REST endpoints
at root paths and WebSocket at /ws with EventEnvelope-shaped events.

Usage:
    cd src/ui/dev && uv run python fixture_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from datetime import UTC, datetime
from uuid import uuid4

import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from scenarios import (
    TEAM_STATUS,
    THREAD_STATE_SNAPSHOTS,
    THREAD_SUMMARIES,
    build_interactive_response,
)
from starlette.requests import Request


log = logging.getLogger("fixture_server")

# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="VaultSpec Fixture Server", version="0.1.0-fixture")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST endpoints ───────────────────────────────────────────────────────────


@app.post("/threads", status_code=201)
async def create_thread(request: Request) -> dict:
    body = await request.json()
    thread_id = uuid4().hex
    title = body.get("title", "New thread")
    log.info("POST /threads — created %s (%s)", thread_id[:8], title)

    # Trigger an interactive response sequence for the new thread
    initial_message = body.get("initial_message", "")
    if initial_message:
        asyncio.create_task(_stream_interactive_response(thread_id, initial_message))

    return {
        "thread_id": thread_id,
        "status": "submitted",
        "nickname": f"fixture-{thread_id[:8]}",
    }


@app.get("/threads")
async def list_threads(offset: int = 0, limit: int = 50) -> dict:
    threads = THREAD_SUMMARIES[offset : offset + limit]
    log.info("GET /threads — returning %d/%d", len(threads), len(THREAD_SUMMARIES))
    return {"threads": threads, "total": len(THREAD_SUMMARIES)}


@app.get("/threads/{thread_id}/state")
async def get_thread_state(thread_id: str) -> dict:
    snapshot = THREAD_STATE_SNAPSHOTS.get(thread_id)
    if snapshot is not None:
        log.info(
            "GET /threads/%s/state — snapshot with %d events",
            thread_id[:8],
            snapshot["last_sequence"],
        )
        return snapshot

    log.info("GET /threads/%s/state — empty snapshot (unknown thread)", thread_id[:8])
    return {
        "thread_id": thread_id,
        "status": "submitted",
        "messages": [],
        "tool_calls": [],
        "pending_permissions": [],
        "artifacts": [],
        "plan": [],
        "agents": [],
        "last_sequence": 0,
        "checkpoint_id": None,
    }


@app.post("/threads/{thread_id}/messages", status_code=202)
async def send_message(thread_id: str, request: Request) -> dict:
    body = await request.json()
    content = body.get("content", "")
    log.info("POST /threads/%s/messages — '%s'", thread_id[:8], content[:50])

    asyncio.create_task(_stream_interactive_response(thread_id, content))
    return {"status": "accepted", "thread_id": thread_id}


@app.get("/team/status")
async def get_team_status() -> dict:
    return TEAM_STATUS


@app.get("/teams")
async def get_teams() -> dict:
    return {"presets": []}


@app.get("/threads/{thread_id}/metadata")
async def get_thread_metadata(thread_id: str) -> dict:
    summary = next((t for t in THREAD_SUMMARIES if t["thread_id"] == thread_id), None)
    if summary:
        return {
            "nickname": summary.get("nickname"),
            "feature_tag": summary.get("feature_tag"),
            "source_branch": summary.get("source_branch"),
        }
    return {"nickname": None, "feature_tag": None, "source_branch": None}


@app.post("/permissions/{request_id}/respond")
async def respond_to_permission(request_id: str, request: Request) -> dict:
    body = await request.json()
    log.info(
        "POST /permissions/%s/respond — option=%s",
        request_id[:16],
        body.get("option_id"),
    )

    thread_id = request_id.split(":", 1)[0] if ":" in request_id else ""
    return {
        "request_id": request_id,
        "accepted": True,
        "thread_id": thread_id,
    }


# ── WebSocket ────────────────────────────────────────────────────────────────

_connections: dict[str, WebSocket] = {}
_subscriptions: dict[str, set[str]] = {}
_client_queues: dict[str, asyncio.Queue[dict]] = {}
_start_time = time.monotonic()


def _broadcast_to_thread(thread_id: str, event: dict) -> None:
    for client_id, subs in _subscriptions.items():
        if thread_id in subs:
            queue = _client_queues.get(client_id)
            if queue is not None:
                queue.put_nowait(event)


async def _stream_interactive_response(thread_id: str, content: str) -> None:
    """Stream a canned agent response sequence to all subscribers."""
    events = build_interactive_response(thread_id, content)
    for event, delay in events:
        if delay > 0:
            await asyncio.sleep(delay)
        _broadcast_to_thread(thread_id, event)


async def _reader_loop(client_id: str, ws: WebSocket) -> None:
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            cmd_type = msg.get("type", "")

            match cmd_type:
                case "subscribe":
                    thread_ids = msg.get("thread_ids", [])
                    _subscriptions[client_id].update(thread_ids)
                    log.info("WS %s subscribed to %s", client_id[:8], thread_ids)

                case "unsubscribe":
                    thread_ids = msg.get("thread_ids", [])
                    _subscriptions[client_id] -= set(thread_ids)
                    log.info("WS %s unsubscribed from %s", client_id[:8], thread_ids)

                case "ping":
                    await ws.send_json(
                        {
                            "type": "heartbeat",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "server_uptime_seconds": round(
                                time.monotonic() - _start_time, 1
                            ),
                            "metadata": None,
                        }
                    )

                case "send_message":
                    tid = msg.get("thread_id", "")
                    content = msg.get("content", "")
                    log.info("WS %s send_message to %s", client_id[:8], tid[:8])
                    asyncio.create_task(_stream_interactive_response(tid, content))

                case "agent_control":
                    action = msg.get("action", "")
                    tid = msg.get("thread_id", "")
                    log.info(
                        "WS %s agent_control %s on %s", client_id[:8], action, tid[:8]
                    )
                    if action == "terminate":
                        _broadcast_to_thread(
                            tid,
                            {
                                "type": "agent_status",
                                "thread_id": tid,
                                "agent_id": "planner-1",
                                "timestamp": datetime.now(UTC).isoformat(),
                                "sequence": 999,
                                "metadata": None,
                                "state": "cancelled",
                                "node_name": "Planner",
                                "detail": "Terminated by user",
                            },
                        )

                case _:
                    log.warning("WS %s unknown command: %s", client_id[:8], cmd_type)

    except WebSocketDisconnect:
        log.info("WS %s disconnected", client_id[:8])
    except Exception as exc:
        log.error("WS %s reader error: %s", client_id[:8], exc)


async def _writer_loop(client_id: str, ws: WebSocket) -> None:
    queue = _client_queues[client_id]
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except Exception:
        pass


async def _heartbeat_loop(client_id: str, ws: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(30.0)
            await ws.send_json(
                {
                    "type": "heartbeat",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "server_uptime_seconds": round(time.monotonic() - _start_time, 1),
                    "metadata": None,
                }
            )
    except Exception:
        pass


def _cleanup_client(client_id: str) -> None:
    _connections.pop(client_id, None)
    _subscriptions.pop(client_id, None)
    _client_queues.pop(client_id, None)
    log.info("Cleaned up client %s", client_id[:8])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    client_id = uuid4().hex

    _connections[client_id] = websocket
    _subscriptions[client_id] = set()
    _client_queues[client_id] = asyncio.Queue()

    log.info("WS %s connected", client_id[:8])

    # Send ConnectedEvent
    await websocket.send_json(
        {
            "type": "connected",
            "client_id": client_id,
            "server_version": "0.1.0-fixture",
            "active_threads": [
                t["thread_id"]
                for t in THREAD_SUMMARIES
                if t.get("agent_state") in ("working", "idle", "submitted")
            ],
            "metadata": None,
        }
    )

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_reader_loop(client_id, websocket))
            tg.create_task(_writer_loop(client_id, websocket))
            tg.create_task(_heartbeat_loop(client_id, websocket))
    except* WebSocketDisconnect:
        pass
    except* Exception as exc_group:
        for exc in exc_group.exceptions:
            if not isinstance(exc, WebSocketDisconnect):
                log.error("WS %s error: %s", client_id[:8], exc)
    finally:
        _cleanup_client(client_id)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Starting fixture server on http://localhost:8000")
    log.info("Vite dev server should proxy /threads, /team, /permissions, /ws here")
    log.info("Run: cd src/ui && npm run dev")
    uvicorn.run(
        "fixture_server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=True,
        reload_dirs=["."],
    )
