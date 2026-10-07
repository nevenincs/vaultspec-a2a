"""What the gateway learns from each way a worker can turn a dispatch down.

Driven against the production worker application and a real ``Executor``, so the
refusals are the ones the worker actually composes rather than statuses written
into a test. The single exception is the server-fault case, which stands for a
worker that failed inside itself or an intermediary that answered for it - the
real worker cannot be asked to produce one on demand, so a small real ASGI app
answers instead.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...domain_config import domain_config
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...testing.catalog_authority import current_execution_metadata
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionType
from ...thread.executable_graph import freeze_graph_definition
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from ..accepted_input import freeze_accepted_input
from ..circuit_breaker import WorkerCircuitBreaker
from ..config import settings
from ..dispatch import safe_dispatch
from ..execution_authority import resolve_execution_authority
from ..worker_management import LazyWorkerSpawner

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from ...worker._dispatch_contract import DispatchCapacityReservation

_TEST_INTERNAL_TOKEN = "dispatch-refusal-test-token"


@pytest.fixture(autouse=True)
def _configure_test_dispatch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give both sides of real worker dispatch the current IPC credential."""
    monkeypatch.setattr(settings, "internal_token", _TEST_INTERNAL_TOKEN)


@asynccontextmanager
async def _real_worker(
    checkpoint_path: Path,
) -> AsyncGenerator[tuple[httpx.AsyncClient, Executor]]:
    """Serve the production worker app over real ASGI with a real executor."""
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        bridge = WorkerBridge("http://control", "dispatch-refusal-test")
        executor = Executor(saver, bridge)
        app = create_worker_app()
        app.state.executor = executor
        async with anyio.create_task_group() as tasks:
            app.state.task_group = tasks
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://worker",
                headers={"Authorization": f"Bearer {_TEST_INTERNAL_TOKEN}"},
            ) as client:
                yield client, executor
            tasks.cancel_scope.cancel()
        await executor.shutdown()
        await bridge.close()


def _spawner() -> LazyWorkerSpawner:
    spawner = LazyWorkerSpawner(
        worker_url="http://worker", worker_port=8001, auto_spawn=False
    )
    spawner.adopt_worker()
    return spawner


def _breaker() -> WorkerCircuitBreaker:
    return WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=30.0)


def _ingest(
    workspace: Path, thread_id: str, dispatch_id: str, *, with_receipt: bool
) -> DispatchRequest:
    """Build the dispatch the gateway really sends, with real graph authority."""
    authority = resolve_execution_authority(
        current_execution_metadata(workspace, required_roles=("mock-coder-success",))
    )
    request = DispatchRequest(
        dispatch_id=dispatch_id,
        action="ingest",
        thread_id=thread_id,
        team_preset="mock-success-single",
        content="a turn",
        workspace_root=str(workspace),
        recursion_limit=25,
        model_assignment=authority.model_assignment,
        graph_definition=freeze_graph_definition(
            load_team_config("mock-success-single", workspace_root=workspace),
            workspace_root=workspace,
        ),
    )
    if not with_receipt:
        return request
    accepted = freeze_accepted_input(request, intent={"content": request.content})
    return request.model_copy(
        update={
            "graph_action_receipt": GraphActionReceipt(
                schema_version="graph-action-v1",
                thread_id=thread_id,
                action_id=f"action-{dispatch_id}",
                action_type=ControlActionType.INGEST,
                payload_fingerprint=control_action_payload_fingerprint(accepted),
                dispatch_id=dispatch_id,
                run_revision=0,
                writer_generation=1,
            )
        }
    )


@pytest.mark.asyncio
async def test_a_full_worker_is_backpressure_and_says_when_to_return(
    tmp_path: Path,
) -> None:
    """Capacity is about the service, and it never counts against its health."""
    async with _real_worker(tmp_path / "capacity.db") as (client, executor):
        for index in range(domain_config.max_concurrent_threads):
            reservation, _reason = await executor.reserve_dispatch_capacity(
                f"held-{index}"
            )
            assert reservation is not None

        breaker = _breaker()
        outcomes = [
            await safe_dispatch(
                client,
                _ingest(tmp_path, "overflow", f"overflow-{attempt}", with_receipt=True),
                breaker,
                _spawner(),
            )
            for attempt in range(4)
        ]

    assert [outcome.failure_type for outcome in outcomes] == [
        FailureType.AT_CAPACITY.value
    ] * 4
    assert {outcome.retry_after_seconds for outcome in outcomes} == {5.0}
    # Four refusals against a two-failure threshold: an unsplit breaker would
    # have opened on the second and rejected everything after it.
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_a_worker_already_running_the_thread_refuses_it_as_busy(
    tmp_path: Path,
) -> None:
    """One run's occupancy is a conflict about that run, not a service fault."""
    async with _real_worker(tmp_path / "busy.db") as (client, executor):
        reservation, _reason = await executor.reserve_dispatch_capacity("busy-thread")
        assert reservation is not None

        breaker = _breaker()
        outcomes = [
            await safe_dispatch(
                client,
                _ingest(
                    tmp_path, "busy-thread", f"second-{attempt}", with_receipt=True
                ),
                breaker,
                _spawner(),
            )
            for attempt in range(3)
        ]

    assert [outcome.failure_type for outcome in outcomes] == [
        FailureType.RUN_BUSY.value
    ] * 3
    assert all(outcome.retry_after_seconds is None for outcome in outcomes)
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_refusals_for_one_run_never_shut_the_other_runs_out(
    tmp_path: Path,
) -> None:
    """The breaker is shared, so what counts against it decides who is served.

    Both refusals are driven past the gateway's own configured failure
    threshold, against the configured breaker rather than a lenient test one,
    because the threshold is what turns "counted" into "everyone is refused".
    A breaker fed by backpressure opens on a busy run or a full worker and then
    rejects every OTHER run's control traffic for the whole recovery window -
    a run's permission answer refused because a different run was executing.

    The proof is the admitted dispatch at the end: the worker has room again,
    and the run that never refused anything is served rather than meeting a
    circuit the other runs opened.
    """
    threshold = settings.cb_failure_threshold
    async with _real_worker(tmp_path / "shared.db") as (client, executor):
        breaker = WorkerCircuitBreaker(
            failure_threshold=threshold,
            recovery_timeout=settings.cb_recovery_timeout_seconds,
        )
        held: list[DispatchCapacityReservation] = []
        reservation, _reason = await executor.reserve_dispatch_capacity("busy-run")
        assert reservation is not None
        held.append(reservation)

        busy = [
            await safe_dispatch(
                client,
                _ingest(tmp_path, "busy-run", f"busy-{attempt}", with_receipt=True),
                breaker,
                _spawner(),
            )
            for attempt in range(threshold + 1)
        ]

        # Fill the rest of the worker so the same breaker now meets capacity.
        for index in range(domain_config.max_concurrent_threads - 1):
            reservation, _reason = await executor.reserve_dispatch_capacity(
                f"held-{index}"
            )
            assert reservation is not None
            held.append(reservation)

        full = [
            await safe_dispatch(
                client,
                _ingest(tmp_path, "other-run", f"full-{attempt}", with_receipt=True),
                breaker,
                _spawner(),
            )
            for attempt in range(threshold + 1)
        ]

        for reservation in held:
            assert await executor.release_dispatch_capacity(reservation)

        admitted = await safe_dispatch(
            client,
            _ingest(tmp_path, "other-run", "other-admitted", with_receipt=True),
            breaker,
            _spawner(),
        )

    assert [outcome.failure_type for outcome in busy] == [
        FailureType.RUN_BUSY.value
    ] * (threshold + 1)
    assert [outcome.failure_type for outcome in full] == [
        FailureType.AT_CAPACITY.value
    ] * (threshold + 1)
    assert admitted.success
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_a_dispatch_refused_before_the_worker_leaves_the_circuit_alone(
    tmp_path: Path,
) -> None:
    """An authority refusal never reaches the worker, so it proves nothing about it.

    The receipt check runs before admission, which is also why it must not take
    the half-open probe on its way out: a request that was never sent cannot be
    the one probe that decides whether the worker is back.
    """
    async with _real_worker(tmp_path / "authority.db") as (client, _executor):
        breaker = _breaker()
        outcome = await safe_dispatch(
            client,
            _ingest(tmp_path, "no-receipt-thread", "no-receipt", with_receipt=False),
            breaker,
            _spawner(),
        )

    assert outcome.failure_type == FailureType.INCOMPATIBLE_STATE.value
    assert breaker.state == "closed"
    assert breaker.pre_dispatch() is not None


@pytest.mark.asyncio
async def test_an_unreachable_worker_opens_the_circuit(tmp_path: Path) -> None:
    """Transport failure is the thing the breaker exists for."""
    breaker = _breaker()
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:1", worker_port=1, auto_spawn=False
    )
    spawner.adopt_worker()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1", timeout=0.25) as client:
        outcomes = [
            await safe_dispatch(
                client,
                _ingest(tmp_path, "dead-thread", f"dead-{attempt}", with_receipt=True),
                breaker,
                spawner,
            )
            for attempt in range(2)
        ]

    assert [outcome.failure_type for outcome in outcomes] == [
        FailureType.UNREACHABLE.value
    ] * 2
    assert breaker.state == "open"


@pytest.mark.asyncio
async def test_a_server_fault_opens_the_circuit(tmp_path: Path) -> None:
    """A 5xx says the far side is broken, which is transport health after all."""
    faulting = FastAPI()

    @faulting.post("/dispatch")
    async def fail() -> JSONResponse:
        return JSONResponse({"detail": "internal worker fault"}, status_code=500)

    breaker = _breaker()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=faulting), base_url="http://worker"
    ) as client:
        outcomes = [
            await safe_dispatch(
                client,
                _ingest(
                    tmp_path, "faulting-thread", f"fault-{attempt}", with_receipt=True
                ),
                breaker,
                _spawner(),
            )
            for attempt in range(2)
        ]

    assert [outcome.failure_type for outcome in outcomes] == [
        FailureType.REJECTED.value
    ] * 2
    assert breaker.state == "open"


@pytest.mark.asyncio
async def test_only_one_dispatch_probes_a_worker_the_circuit_has_shut_out(
    tmp_path: Path,
) -> None:
    """Recovery tests the worker with one request, not with the flood again.

    The probe is held open by a worker that has the thread busy only after the
    first dispatch is answered, so the ordering here is the honest one: while a
    probe is unsettled nothing else is admitted, and once it settles the circuit
    is open to everyone again.
    """
    async with _real_worker(tmp_path / "probe.db") as (client, _executor):
        breaker = WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        breaker.force_open()
        assert breaker.state == "half_open"

        # Take the single probe without settling it, exactly as an in-flight
        # dispatch holds it, and prove the next caller is refused.
        probe = breaker.pre_dispatch()
        assert probe is not None
        blocked = await safe_dispatch(
            client,
            _ingest(tmp_path, "probe-thread", "probe-blocked", with_receipt=True),
            breaker,
            _spawner(),
        )
        assert blocked.failure_type == FailureType.CIRCUIT_OPEN.value

        breaker.release_probe(probe)
        admitted = await safe_dispatch(
            client,
            _ingest(tmp_path, "probe-thread", "probe-admitted", with_receipt=True),
            breaker,
            _spawner(),
        )

    assert admitted.success
    assert breaker.state == "closed"
