"""Live Postgres verification for WebSocket reconnect + snapshot recovery."""

import asyncio
import json
import time

import httpx
import pytest
from websockets.asyncio.client import connect

from .conftest import _stop_process
from .test_permission_durability_live import (
    _prepare_workspace,
    _select_certifying_provider,
    _start_manual_stack,
)

pytestmark = pytest.mark.live

_THREAD_EVENT_TIMEOUT = 120.0


async def _create_autonomous_thread(
    *,
    gateway_url: str,
    workspace_root: str,
    feature_tag: str,
) -> str:
    timeout = httpx.Timeout(60.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        create_resp = await client.post(
            f"{gateway_url}/api/threads",
            json={
                "initial_message": "Implement a backend improvement.",
                "team_preset": "vaultspec-adaptive-coder",
                "autonomous": True,
                "metadata": {
                    "workspace_root": workspace_root,
                    "feature_tag": feature_tag,
                },
            },
        )
        create_resp.raise_for_status()
        return create_resp.json()["thread_id"]


async def _send_followup_message(
    *, gateway_url: str, thread_id: str, content: str
) -> None:
    timeout = httpx.Timeout(60.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{gateway_url}/api/threads/{thread_id}/messages",
            json={"content": content},
        )
        resp.raise_for_status()
        assert resp.json()["accepted"] is True


async def _recv_json(websocket) -> dict:
    return json.loads(await websocket.recv())


async def _wait_for_thread_event(websocket, thread_id: str) -> dict:
    deadline = time.monotonic() + _THREAD_EVENT_TIMEOUT
    while time.monotonic() < deadline:
        payload = await asyncio.wait_for(_recv_json(websocket), timeout=10.0)
        if payload.get("thread_id") == thread_id and payload.get("type") not in {
            "connected",
            "heartbeat",
        }:
            return payload
    raise AssertionError("Timed out waiting for a thread-scoped WebSocket event")


async def _wait_for_durable_snapshot(
    gateway_url: str,
    thread_id: str,
    *,
    minimum_sequence: int,
) -> dict:
    timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
    deadline = time.monotonic() + _THREAD_EVENT_TIMEOUT
    last_snapshot = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{gateway_url}/api/threads/{thread_id}/state")
            resp.raise_for_status()
            snapshot = resp.json()
            if (
                snapshot.get("replay_status") == "durable"
                and snapshot.get("snapshot_complete") is True
                and snapshot.get("last_sequence", 0) >= minimum_sequence
            ):
                return snapshot
            last_snapshot = snapshot
            await asyncio.sleep(1.0)

    raise AssertionError(f"Timed out waiting for durable snapshot: {last_snapshot!r}")


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(480)
async def test_websocket_reconnect_uses_snapshot_recovery_not_implicit_replay(
    postgres_sqlalchemy_url,
    postgres_checkpoint_url,
    tmp_path,
):
    provider = _select_certifying_provider()
    feature_tag = "replay-reconnect"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    gateway = None
    worker = None

    try:
        gateway, worker, gateway_url, _env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=postgres_checkpoint_url,
        )
        thread_id = await _create_autonomous_thread(
            gateway_url=gateway_url,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )

        ws_url = gateway_url.replace("http://", "ws://", 1) + "/ws"
        async with connect(ws_url) as websocket:
            connected = await _recv_json(websocket)
            assert connected["type"] == "connected"

            await websocket.send(
                json.dumps({"type": "subscribe", "thread_ids": [thread_id]})
            )
            await _send_followup_message(
                gateway_url=gateway_url,
                thread_id=thread_id,
                content="Continue with the backend implementation and report progress.",
            )
            event = await _wait_for_thread_event(websocket, thread_id)
            event_sequence = event["sequence"]

        snapshot = await _wait_for_durable_snapshot(
            gateway_url,
            thread_id,
            minimum_sequence=event_sequence,
        )
        assert snapshot["thread_id"] == thread_id
        assert snapshot["snapshot_complete"] is True
        assert snapshot["replay_status"] == "durable"
        assert snapshot["last_sequence"] >= event_sequence

        await _stop_process(worker)
        worker = None

        async with connect(ws_url) as websocket:
            connected = await _recv_json(websocket)
            assert connected["type"] == "connected"
            await websocket.send(
                json.dumps({"type": "subscribe", "thread_ids": [thread_id]})
            )
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(_recv_json(websocket), timeout=1.0)

        recovered_snapshot = await _wait_for_durable_snapshot(
            gateway_url,
            thread_id,
            minimum_sequence=event_sequence,
        )
        assert recovered_snapshot["thread_id"] == thread_id
        assert recovered_snapshot["replay_status"] == "durable"
        assert recovered_snapshot["last_sequence"] >= event_sequence
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)
