"""Cancellation remains deliverable while the worker circuit is open."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from ...ipc.schemas import DispatchRequest
from ..circuit_breaker import WorkerCircuitBreaker
from ..dispatch import safe_dispatch

if TYPE_CHECKING:
    from ..worker_management import LazyWorkerSpawner


@pytest.mark.asyncio
async def test_cancel_dispatch_bypasses_open_circuit() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    circuit = WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=3600)
    circuit.force_open()
    spawner = cast(
        "LazyWorkerSpawner",
        SimpleNamespace(
            ensure_worker=AsyncMock(), demand_ready_event=None, spawned=True
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://worker"
    ) as client:
        outcome = await safe_dispatch(
            client,
            DispatchRequest(action="cancel", thread_id="run", recursion_limit=1),
            circuit,
            spawner,
        )

    assert outcome.success
    assert len(requests) == 1
    assert json.loads(requests[0].content)["action"] == "cancel"
    assert circuit.state == "closed"
