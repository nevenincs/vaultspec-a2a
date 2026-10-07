"""Cancellation remains deliverable while the worker circuit is open."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...ipc.schemas import DispatchRequest
from ...testing import adopted_spawner, served_worker
from ..circuit_breaker import WorkerCircuitBreaker
from ..dispatch import safe_dispatch

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@pytest.mark.asyncio
async def test_cancel_dispatch_bypasses_open_circuit(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The production worker admits a cancel that the open circuit would refuse."""
    circuit = WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=3600)
    circuit.force_open()
    cancel = DispatchRequest(action="cancel", thread_id="run")

    async with served_worker(checkpointer) as worker:
        outcome = await safe_dispatch(worker.client, cancel, circuit, adopted_spawner())
        admitted = cancel.dispatch_id in worker.app.state.dispatch_ids

    assert outcome.success
    assert admitted
    assert circuit.state == "closed"
