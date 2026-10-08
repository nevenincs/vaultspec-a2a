"""The in-process worker the api suites dispatch to answers a READY worker body.

Every ``make_app`` suite reaches "the worker" through the in-process ASGI app in
``conftest``, and several of them assert readiness that is derived from a real
probe of it. Readiness is not a status code: ``probe_worker_health`` accepts an
exact ``200`` whose body passes the shared role-aware rule, so an in-process
worker whose ``/health`` omits ``service`` answers ``200`` and is still judged
un-ready. That divergence is invisible at the point it is introduced - the
harness keeps answering - and surfaces only as a readiness wait that never
settles in whichever suite happens to depend on it.

Pinned here against the production primitive the gateway uses, so the harness is
held to the production contract directly rather than through a 60-second
readiness wait somewhere else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...control._worker_health import probe_worker_health
from ...lifecycle.discovery import health_payload_ready
from .conftest import SessionFactory, make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_WORKER_URL = "http://test-worker:8001"


@pytest.mark.asyncio(loop_scope="function")
async def test_in_process_worker_health_is_probe_ready(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The production worker-health probe judges the harness worker healthy."""
    _app, _hub, worker, _cp = make_app(session_factory, checkpointer)

    probe = await probe_worker_health(
        _WORKER_URL, client=worker.client, internal_token=None
    )

    assert probe.healthy is True, probe.body
    assert probe.body is not None
    assert health_payload_ready(probe.body, "worker") is True, probe.body
    # The role name is the half a status-only verdict cannot supply, and the half
    # the harness body was missing.
    assert probe.body["service"] == "worker", probe.body
    assert probe.body["status"] == "ok", probe.body


@pytest.mark.asyncio(loop_scope="function")
async def test_in_process_worker_health_carries_the_pairing_evidence(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Its body carries the fields the gateway's adoption and pairing paths read.

    ``_classify_worker_body`` and the authenticated readiness verb read the
    worker's reported target and pairing identity out of this body. A harness
    worker that omits them lets a suite assert on pairing disclosure that the real
    worker would have populated, so the keys are present here by contract.
    """
    _app, _hub, worker, _cp = make_app(session_factory, checkpointer)

    response = await worker.client.get("/health")

    assert response.status_code == 200, response.text
    body = response.json()
    for field in (
        "gateway_url",
        "gateway_pairing_warning",
        "worker_port",
        "database_backend",
        "checkpoint_backend",
        "paired_gateway_lifetime",
        "worker_generation",
    ):
        assert field in body, (field, body)
