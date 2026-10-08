"""The verdict subscriber's start condition and the run-start refusal it binds.

A document gate parks on an engine proposal and can be resumed only by the
authoring verdict subscriber, so a gateway running none cannot finish a
document-authoring run. These tests hold both halves of that binding over real
objects: a real engine record and a real proving listener decide whether the
production start path runs a subscriber, and the real ``POST /v1/runs`` verb
over a real socket decides what a document-authoring request is answered with.

Real throughout - a genuinely provisioned workspace (an actual
``vaultspec-core install``), the real discovery boundary with its filesystem
provenance and proof-of-possession probe, the real ``VerdictSubscriber`` on a
real task, and the gateway's own in-process dispatch receiver. The subscriber's
own loop re-resolves the engine every pass, so the task started here stays
alive against a peer that serves only ``/health``; it is cancelled before the
test returns.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from ...authoring.tests._engine_peer import (
    engine_health_listener,
    private_engine_dir,
    write_engine_record,
)
from ...cli.provision import provision_workspace
from ...control.run_start_policy import required_role_ids
from ...team.team_config import load_team_config
from ...testing import (
    DEFAULT_TEAM_PRESET,
    actor_tokens_body,
    async_catalog_run_fields,
    role_tokens,
    serve_on_loopback,
    settings_override,
)
from ..app import _start_verdict_subscriber
from .conftest import SessionFactory, make_app

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ...conftest import ExternalPrerequisiteRule

_AUTHORING = "vaultspec-adr-research"
_SUBSCRIBER_UNAVAILABLE = "authoring_subscriber_unavailable"


@pytest.fixture(autouse=True)
def _require_core(external_prerequisite: ExternalPrerequisiteRule) -> None:
    """The authoring cases provision a real workspace with a genuine core install."""
    external_prerequisite("vaultspec-core")


async def _authoring_body(
    client: httpx.AsyncClient, workspace_root: Path, *, run_id: str
) -> dict[str, Any]:
    """A document-authoring request complete but for the gateway's own condition.

    Every request-side precondition is satisfied - a target feature, one actor
    token per required role, a provisioned workspace and a selection served for
    it - so the only thing left that can refuse the run is whether this gateway
    can finish it.
    """
    fields = await async_catalog_run_fields(client, workspace_root=str(workspace_root))
    roles = tuple(required_role_ids(load_team_config(_AUTHORING)))
    return {
        "team_preset": _AUTHORING,
        "message": "research the thing",
        "feature_tag": "verdict-subscriber-gate",
        "actor_tokens": actor_tokens_body(role_tokens(roles)),
        "metadata": {"workspace_root": str(workspace_root)},
        "run_id": run_id,
        "selection": fields["selection"],
    }


def _provisioned(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    result = provision_workspace(workspace)
    assert result.ok, result.harness.reasons
    return workspace


async def _start_subscriber(
    app: FastAPI,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> asyncio.Task[None] | None:
    """Run the production start path against this app's own runtime."""
    return await _start_verdict_subscriber(
        app,
        session_factory,
        checkpointer,
        app.state.worker_client,
        app.state.circuit_breaker,
        app.state.worker_spawner,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_authoring_run_is_refused_when_no_verdict_subscriber_runs(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, tmp_path: Path
) -> None:
    """A gateway with no subscriber refuses the document topology it cannot finish.

    The refusal is typed, not prose: the dashboard branches on the code to tell
    "this gateway cannot serve this topology" from a request it should fix.
    """
    workspace = _provisioned(tmp_path)
    app, _hub, worker, _cp = make_app(session_factory, checkpointer)
    assert getattr(app.state, "verdict_subscriber_task", None) is None

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        response = await client.post(
            "/v1/runs",
            json=await _authoring_body(client, workspace, run_id="run-no-subscriber"),
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == _SUBSCRIBER_UNAVAILABLE
    # Refused before anything was dispatched: no durable run, no worker turn.
    assert worker.dispatches == []


@pytest.mark.asyncio(loop_scope="function")
async def test_a_coding_run_is_unaffected_by_the_subscriber_gate(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The gate binds document topologies only; a coding run still starts."""
    app, _hub, worker, _cp = make_app(session_factory, checkpointer)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        fields = await async_catalog_run_fields(client)
        response = await client.post(
            "/v1/runs",
            json={
                "team_preset": DEFAULT_TEAM_PRESET,
                "message": "build it",
                "run_id": "run-coding-unaffected",
                **fields,
            },
        )

    assert response.status_code == 201, response.text
    assert len(worker.dispatches) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_no_discoverable_engine_record_starts_no_subscriber(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, tmp_path: Path
) -> None:
    """With no engine record there is nothing to subscribe to, so nothing runs."""
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)

    with settings_override(engine_service_json=tmp_path / "absent-service.json"):
        task = await _start_subscriber(app, session_factory, checkpointer)

    assert task is None
    assert app.state.verdict_subscriber_task is None


@pytest.mark.asyncio(loop_scope="function")
async def test_a_discoverable_engine_record_starts_the_subscriber_and_admits_the_run(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, tmp_path: Path
) -> None:
    """A proven engine record starts the subscriber, and the run is then admitted.

    The same request the case above refuses, answered by the same code on the
    same app: only the engine record differs, which is the condition under
    proof.
    """
    workspace = _provisioned(tmp_path)
    app, _hub, worker, _cp = make_app(session_factory, checkpointer)

    with private_engine_dir() as engine_dir, engine_health_listener() as port:
        record = engine_dir / "service.json"
        write_engine_record(record, port)
        with settings_override(engine_service_json=record):
            task = await _start_subscriber(app, session_factory, checkpointer)
            assert task is not None
            assert app.state.verdict_subscriber_task is task
            assert not task.done()
            try:
                async with (
                    serve_on_loopback(app) as base,
                    httpx.AsyncClient(base_url=base, timeout=30.0) as client,
                ):
                    response = await client.post(
                        "/v1/runs",
                        json=await _authoring_body(
                            client, workspace, run_id="run-with-subscriber"
                        ),
                    )
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert response.status_code == 201, response.text
    assert response.json()["eligible"] is True
    assert len(worker.dispatches) == 1
