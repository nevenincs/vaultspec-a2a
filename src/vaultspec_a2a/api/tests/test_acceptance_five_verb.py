"""Acceptance coverage for the six-member gateway whitelist.

In-process, real-component coverage of the acceptance criteria that do NOT need
the live dashboard engine or Docker (both absent here). No mocks: a real
``Executor`` runs a real multi-role compiled graph against a real file-backed
``AsyncSqliteSaver``; the gateway control surface then reads that durable state back
over a real TCP socket.

Covers: per-role run through the surface, ``run-status`` as the authoritative
recovery snapshot, restart recovery (a fresh gateway on the same durable
checkpoint returns the same snapshot), zero ``.vault/`` writes across the run,
and no actor token in any captured log record (closing the ``model_dump``
residual).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, override

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.accepted_input import freeze_accepted_input
from ...control.execution_authority import resolve_execution_authority
from ...control.tests._catalog_authority import current_execution_metadata
from ...database.thread_repository import create_thread
from ...ipc.schemas import DispatchRequest
from ...providers.team_selection import model_assignment_digest
from ...team.team_config import load_team_config
from ...tests._write_authority import make_test_write_authority
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from .clarification_harness import new_state_graph
from .conftest import SessionFactory, async_catalog_run_fields, make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path

    from ...thread.state import TeamState
    from ...worker.graph_lifecycle import RegisteredCompiledGraph

# Every dispatch names an active project, as a real one does. This package's own
# directory is real, absolute, and present on either platform.
_WORKSPACE = str(pathlib.Path(__file__).resolve().parent)
_CODER_TOKEN = "secret-coder-acceptance"
_REVIEWER_TOKEN = "secret-reviewer-acceptance"
_BEARER = "secret-bearer-acceptance"
_PRESET = "mock-success-multi"


@dataclass(frozen=True, slots=True)
class _MultiroleFixture:
    """Durable inputs and before-snapshot for the multi-role recovery proof."""

    vault_root: Path
    before: list[str]
    thread_id: str
    checkpoint_path: str
    definition: FrozenGraphDefinition
    model_assignment: dict[str, dict[str, Any]]


# ---------------------------------------------------------------------------
# Live-socket helpers
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _live_server(app: object) -> AsyncGenerator[str]:
    config = uvicorn.Config(
        cast("Any", app), host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started and server.servers:
                break
            await asyncio.sleep(0.01)
        assert server.started and server.servers, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5.0)


def _bridge() -> WorkerBridge:
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _b(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.post("/internal/heartbeat")
    async def _h(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    bridge = WorkerBridge(api_url="http://control:8000", worker_id="accept-worker")
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://control:8000"
    )
    return bridge


def _install_multirole_graph(
    executor: Executor,
    thread_id: str,
    definition: FrozenGraphDefinition,
    model_assignment: dict[str, dict[str, Any]],
) -> None:
    """A real two-role graph: a coder then a reviewer, each attributing a message."""

    async def coder(state: TeamState) -> dict[str, Any]:
        return {"messages": [AIMessage(content="coder drafted", name="coder")]}

    async def reviewer(state: TeamState) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content="reviewer approved", name="reviewer")],
            "next": "FINISH",
        }

    builder = new_state_graph()
    builder.add_node("coder", coder)
    builder.add_node("reviewer", reviewer)
    builder.add_edge("__start__", "coder")
    builder.add_edge("coder", "reviewer")
    builder.add_edge("reviewer", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(
        checkpointer=executor._checkpointer
    )

    cache_key = (
        _PRESET,
        _WORKSPACE,
        False,
        model_assignment_digest(model_assignment),
        definition.digest(),
    )
    executor.register_compiled_graph(thread_id, cache_key, graph)


def _vault_write_events(vault_root: Path) -> list[str]:
    """Snapshot vault file mtimes+sizes for a before/after zero-write comparison."""
    events: list[str] = []
    if not vault_root.exists():
        return events
    for path in vault_root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            events.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    return events


async def _read_run_status(client: httpx.AsyncClient, thread_id: str) -> dict[str, Any]:
    response = await client.get(f"/v1/runs/{thread_id}")
    assert response.status_code == 200
    return response.json()


async def _prepare_multirole_fixture(
    session_factory: SessionFactory,
    tmp_path: Path,
) -> _MultiroleFixture:
    """Create the durable run inputs shared by both recovery reads."""
    vault_root = tmp_path / ".vault"
    vault_root.mkdir()
    (vault_root / "seed.md").write_text("do not touch", encoding="utf-8")
    before = _vault_write_events(vault_root)

    thread_id = "accept-run"
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=ThreadStatus.RUNNING,
            title="acceptance",
            team_preset=_PRESET,
        )
        await session.commit()

    checkpoint_path = str(tmp_path / "checkpoints.db")
    workspace = pathlib.Path(_WORKSPACE)
    definition = freeze_graph_definition(
        load_team_config(_PRESET, workspace_root=workspace),
        workspace_root=workspace,
    )
    model_assignment = resolve_execution_authority(
        current_execution_metadata(
            workspace,
            required_roles=("mock-planner", "mock-coder-success", "mock-reviewer"),
        )
    ).model_assignment
    return _MultiroleFixture(
        vault_root=vault_root,
        before=before,
        thread_id=thread_id,
        checkpoint_path=checkpoint_path,
        definition=definition,
        model_assignment=model_assignment,
    )


async def _dispatch_multirole_run(
    session_factory: SessionFactory,
    fixture: _MultiroleFixture,
) -> dict[str, Any]:
    """Dispatch the real graph and read its first durable status snapshot."""
    bundle = ActorTokenBundle(
        tokens={"coder": _CODER_TOKEN, "reviewer": _REVIEWER_TOKEN},
        engine_bearer=_BEARER,
    )
    async with AsyncSqliteSaver.from_conn_string(fixture.checkpoint_path) as cp:
        await cp.setup()
        bridge = _bridge()
        executor: Executor | None = None
        try:
            executor = Executor(checkpointer=cp, bridge=bridge)
            _install_multirole_graph(
                executor,
                fixture.thread_id,
                fixture.definition,
                fixture.model_assignment,
            )
            req = DispatchRequest(
                action="ingest",
                workspace_root=_WORKSPACE,
                thread_id=fixture.thread_id,
                content="build and review",
                team_preset=_PRESET,
                graph_definition=fixture.definition,
                model_assignment=fixture.model_assignment,
                recursion_limit=10,
                actor_tokens=bundle,
            )
            accepted = freeze_accepted_input(
                req, intent={"content": "build and review"}
            )
            receipt = GraphActionReceipt(
                schema_version="graph-action-v1",
                thread_id=fixture.thread_id,
                action_id=f"{fixture.thread_id}-action",
                action_type=ControlActionType.INGEST,
                payload_fingerprint=control_action_payload_fingerprint(accepted),
                dispatch_id=req.dispatch_id,
                run_revision=0,
                writer_generation=1,
            )
            req = req.model_copy(update={"graph_action_receipt": receipt})
            with caplog_all() as records:
                await executor.handle_dispatch(req)
        finally:
            await bridge.close()
            if executor is not None:
                await executor.shutdown()

        _assert_no_token(records)
        app, _agg, _worker, _cp = make_app(session_factory, cp)
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base) as client,
        ):
            return await _read_run_status(client, fixture.thread_id)


async def _read_restart_status(
    session_factory: SessionFactory,
    fixture: _MultiroleFixture,
) -> dict[str, Any]:
    """Read the same snapshot through a fresh gateway/checkpointer pair."""
    async with AsyncSqliteSaver.from_conn_string(fixture.checkpoint_path) as restart_cp:
        app2, _a2, _w2, _c2 = make_app(session_factory, restart_cp)
        async with (
            _live_server(app2) as base2,
            httpx.AsyncClient(base_url=base2) as client2,
        ):
            return await _read_run_status(client2, fixture.thread_id)


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_multirole_run_status_recovery_and_zero_vault_writes(
    session_factory: SessionFactory, tmp_path: Path
) -> None:
    fixture = await _prepare_multirole_fixture(session_factory, tmp_path)
    body = await _dispatch_multirole_run(session_factory, fixture)
    assert body["api_version"] == "v1"
    assert body["run_id"] == fixture.thread_id
    assert body["topology"]["team_preset"] == _PRESET
    assert isinstance(body["roles"], list)
    assert isinstance(body["proposal_ids"], list)
    assert body["checkpoint_id"] is not None

    body2 = await _read_restart_status(session_factory, fixture)
    assert body2["run_id"] == fixture.thread_id
    assert body2["topology"]["team_preset"] == _PRESET
    assert body2["checkpoint_id"] == body["checkpoint_id"]

    after = _vault_write_events(fixture.vault_root)
    assert fixture.before == after, "the run must not write to .vault/"


def _assert_no_token(records: list[logging.LogRecord]) -> None:
    """Assert no actor token appears on any captured log record."""
    for record in records:
        blob = " ".join([record.getMessage(), repr(record.args), repr(record.__dict__)])
        for secret in (_CODER_TOKEN, _REVIEWER_TOKEN, _BEARER):
            assert secret not in blob, f"token leaked in log {record.name}"


@contextlib.contextmanager
def caplog_all() -> Generator[list[logging.LogRecord]]:
    """Capture every log record emitted on the root logger during the block."""
    records: list[logging.LogRecord] = []

    class _Sink(logging.Handler):
        @override
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Sink(level=logging.DEBUG)
    root = logging.getLogger()
    prior = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(prior)


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_carries_no_token_into_logs(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """No actor token appears in captured logs across a dispatched run-start."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    bundle = {
        "tokens": {"coder": _CODER_TOKEN, "reviewer": _REVIEWER_TOKEN},
        "engine_bearer": _BEARER,
    }
    async with _live_server(app) as base, httpx.AsyncClient(base_url=base) as client:
        # Derived OUTSIDE the capture: the catalog probe is setup, not the run
        # under test, and the assertion below is sharpest when the captured window
        # holds only the run-start that carries the tokens.
        run_fields = await async_catalog_run_fields(client)
        with caplog_all() as records:
            resp = await client.post(
                "/v1/runs",
                json={
                    "team_preset": _PRESET,
                    "message": "go",
                    "autonomous": True,
                    "actor_tokens": bundle,
                    "run_id": "accept-token-log",
                    **run_fields,
                },
            )
            assert resp.status_code == 201, resp.text
            # The worker received the tokens on the dispatch (transport works)...
            assert worker.dispatches[-1]["actor_tokens"]["tokens"]["coder"] == (
                _CODER_TOKEN
            )

    # ...but no token appears in any captured log line (the model_dump residual).
    _assert_no_token(records)
