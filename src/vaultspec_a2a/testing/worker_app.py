"""The production worker application, served in-process over a real ``Executor``.

A control-plane test that dispatches to a worker needs a worker whose answers are
the ones production composes: the dispatch route, its bearer check, its admission
of a repeated dispatch id and the executor's own capacity and graph lifecycle.
:func:`served_worker` serves ``create_worker_app()`` over ``httpx.ASGITransport``
with a real ``Executor`` and a real ``WorkerBridge``, and yields the client a
gateway would dispatch through.

Unless the caller supplies a bridge, the worker reports to a loopback port
nothing listens on: its callback frames are undeliverable and stay buffered on
the bridge, where a test can read them.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
from langchain_core.messages import AIMessage

from ..control.config import settings
from ..control.execution_authority import resolve_execution_authority
from ..domain_config import domain_config
from ..team.team_config import load_team_config
from ..thread.executable_graph import freeze_graph_definition
from ..utils import bearer_header
from ..worker.app import create_worker_app
from ..worker.executor import Executor
from ..worker.ipc import WorkerBridge
from .catalog_authority import current_execution_metadata
from .environment import settings_override
from .gateway_verbs import DEFAULT_TEAM_PRESET
from .graph import add_test_node, compile_test_graph, new_state_graph

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable, Mapping

    from fastapi import FastAPI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..worker.graph_lifecycle import GraphCompilationKey, RegisteredCompiledGraph

__all__ = ["ServedWorker", "capacity_holders", "served_worker"]

_WORKER_URL = "http://worker"
_UNREACHABLE_GATEWAY_URL = "http://127.0.0.1:9"


@dataclass(frozen=True, slots=True)
class ServedWorker:
    """One served worker: the client that reaches it and what it is built from."""

    client: httpx.AsyncClient
    app: FastAPI
    executor: Executor
    bridge: WorkerBridge


def capacity_holders() -> tuple[str, ...]:
    """Thread ids that together take every run slot a worker has."""
    slots = range(domain_config.max_concurrent_threads)
    return tuple(f"held-{index}" for index in slots)


def _install_receipt_graph(
    executor: Executor, checkpointer: AsyncSqliteSaver, thread_id: str
) -> None:
    """Register a real one-node graph so a resume crosses the executor's application."""

    async def complete(_state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage(content="resumed")], "next": "FINISH"}

    builder = new_state_graph()
    add_test_node(builder, "worker", complete)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    workspace = Path.cwd()
    definition = freeze_graph_definition(
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=workspace),
        workspace_root=workspace,
    )
    executor.register_compiled_graph(
        thread_id,
        (
            DEFAULT_TEAM_PRESET,
            str(workspace),
            False,
            resolve_execution_authority(
                current_execution_metadata(workspace)
            ).model_assignment_digest,
            definition.digest(),
        ),
        compile_test_graph(builder, checkpointer=checkpointer),
    )


@contextlib.asynccontextmanager
async def served_worker(
    checkpointer: AsyncSqliteSaver,
    *,
    token: str | None = None,
    gateway: FastAPI | None = None,
    bridge: WorkerBridge | None = None,
    held_threads: Iterable[str] = (),
    receipt_threads: Iterable[str] = (),
    graphs: Mapping[str, tuple[GraphCompilationKey, RegisteredCompiledGraph]]
    | None = None,
    drain_dispatches: bool = False,
) -> AsyncGenerator[ServedWorker]:
    """Serve the production worker application for the duration of the block.

    *token* seats the dispatch credential on the settings the worker verifies
    against for the block; the client presents whatever credential is seated, and
    none when no credential is. *gateway*, when given, takes the served client as
    its ``worker_client``. *bridge* is the callback bridge the executor reports
    through, left open for its owner to close; without one the worker owns a
    bridge to a gateway nothing answers.

    *held_threads* take their dispatch capacity through the executor's own
    reservation verb, so the worker refuses the next dispatch for the reason it
    would refuse a real concurrent turn. *receipt_threads* register a graph that
    completes on resume, so a dispatch for them crosses the executor's
    application receipt. *graphs* register an already compiled graph per thread.

    Dispatched work is cancelled when the block ends, so a run nothing will
    finish cannot hold the block open; *drain_dispatches* waits for it instead.
    """
    seat = (
        settings_override(internal_token=token)
        if token is not None
        else contextlib.nullcontext()
    )
    with seat:
        worker_bridge = (
            WorkerBridge(_UNREACHABLE_GATEWAY_URL, "served-worker")
            if bridge is None
            else bridge
        )
        executor = Executor(checkpointer, worker_bridge)
        try:
            for thread_id in receipt_threads:
                _install_receipt_graph(executor, checkpointer, thread_id)
            for thread_id, (key, graph) in (graphs or {}).items():
                executor.register_compiled_graph(thread_id, key, graph)
            for thread_id in held_threads:
                reservation, reason = await executor.reserve_dispatch_capacity(
                    thread_id
                )
                assert reservation is not None, reason
            app = create_worker_app()
            app.state.executor = executor
            async with anyio.create_task_group() as tasks:
                app.state.task_group = tasks
                credential = settings.internal_token
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url=_WORKER_URL,
                    headers=None if credential is None else bearer_header(credential),
                ) as client:
                    if gateway is not None:
                        gateway.state.worker_client = client
                    yield ServedWorker(client, app, executor, worker_bridge)
                if not drain_dispatches:
                    tasks.cancel_scope.cancel()
        finally:
            await executor.shutdown()
            if bridge is None:
                await worker_bridge.close()
