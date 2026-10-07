"""Real gateway and worker coverage for cancellation during a blocked stream."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from ..database import CONTROL_ACTION_LEASE_TTL
from ..testing import (
    fetch_in_process_selection,
    json_object,
    reap_process,
    required_bool,
    required_text,
    wait_for_run_status,
)
from ._state import thread_state
from .harness import build_service_stack

if TYPE_CHECKING:
    from ..conftest import ExternalPrerequisiteRule
    from ..providers import JsonObject
    from .harness import ServiceStack

_LAZY_GATEWAY_LOG = "lazy-gateway.log"


def _cancel_receipt(stack: ServiceStack, run_id: str) -> tuple[str, str, str | None]:
    with sqlite3.connect(stack.runtime_dir / "service.db") as connection:
        row = connection.execute(
            "SELECT dispatch_id, result_status, applied_at FROM control_actions "
            "WHERE thread_id = ? AND action_type = 'cancel'",
            (run_id,),
        ).fetchone()
    assert row is not None
    return row


@pytest.mark.parametrize(
    "restart", [False, True], ids=["lazy-start", "restart-redelivery"]
)
def test_cancellation_survives_fresh_worker(
    external_prerequisite: ExternalPrerequisiteRule,
    restart: bool,
) -> None:
    """A fresh worker consumes the durable cancel, including after lost delivery."""
    external_prerequisite("docker")
    stack = build_service_stack()
    try:
        if restart:
            stack.start()
        else:
            stack._ensure_runtime_dir()
            stack._start_infra()
            stack.start_gateway(auto_spawn_worker=True, log_name=_LAZY_GATEWAY_LOG)
        workspace = stack.runtime_dir / "fresh-worker-cancel"
        workspace.mkdir()
        run_id = f"fresh-worker-{uuid4().hex}"
        with stack.gateway_client(timeout=120.0) as client:
            response = client.post(
                "/v1/runs",
                json={
                    "run_id": run_id,
                    "message": "Wait for cancellation.",
                    "team_preset": "deterministic-cancel-window",
                    "selection": fetch_in_process_selection(client, str(workspace)),
                    "metadata": {"workspace_root": str(workspace)},
                    "autonomous": True,
                },
            )
            assert response.status_code == 201, response.text
            running = wait_for_run_status(
                lambda: thread_state(stack, run_id), _is_running, timeout=30.0
            )
            health = stack.health()
            assert health["checks"]["worker"]["status"] == "ok", health
            stack.record("fresh-worker-running", running)
            if restart:
                assert stack._worker_proc is not None
                reap_process(stack._worker_proc)
                stack._worker_proc = None
            cancelled = client.post(f"/v1/runs/{run_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["accepted"] is True
        receipt = _cancel_receipt(stack, run_id)
        stack.record("accepted-cancel-receipt", receipt)
        if restart:
            assert receipt[2] is None
            stack.crash_gateway()
            stack.start_gateway(auto_spawn_worker=True, log_name=_LAZY_GATEWAY_LOG)
        terminal = wait_for_run_status(
            lambda: thread_state(stack, run_id),
            _is_cancelled,
            timeout=(
                CONTROL_ACTION_LEASE_TTL.total_seconds() + 60.0 if restart else 30.0
            ),
        )
        settled = _cancel_receipt(stack, run_id)
        stack.record("fresh-worker-terminal", terminal)
        stack.record("settled-cancel-receipt", settled)
        assert settled[0] == receipt[0]
        assert settled[1] in {"cancelled_ceased", "cancelled_no_active_work"}
        assert settled[2] is not None
    finally:
        stack.stop()


def _is_running(state: JsonObject) -> bool:
    return state.get("status") == "running"


def _is_cancelled(state: JsonObject) -> bool:
    return state.get("status") == "cancelled"


def test_blocked_deterministic_stream_cancellation_settles_terminally(
    service_stack: ServiceStack,
) -> None:
    """A real cancellation interrupts the deterministic stream without a watchdog."""
    workspace = service_stack.runtime_dir / "blocked-stream-cancellation"
    workspace.mkdir(parents=True, exist_ok=True)
    workspace_root = str(Path(workspace))
    run_id = f"blocked-cancel-{uuid4().hex}"
    with service_stack.gateway_client(timeout=30.0) as client:
        started = client.post(
            "/v1/runs",
            json={
                "run_id": run_id,
                "message": "Block in the deterministic cancellation window.",
                "team_preset": "deterministic-cancel-window",
                "selection": fetch_in_process_selection(client, workspace_root),
                "metadata": {"workspace_root": workspace_root},
                "autonomous": True,
            },
        )
        started.raise_for_status()
        created = json_object(started.json(), at="blocked cancellation run start")
    assert (
        required_text(created, "run_id", at="blocked cancellation run start") == run_id
    )

    running = wait_for_run_status(
        lambda: thread_state(service_stack, run_id), _is_running, timeout=30.0
    )
    service_stack.record(f"blocked-cancel-running:{run_id}", running)

    cancelling = json_object(
        service_stack.cancel_thread(run_id), at="blocked cancellation response"
    )
    assert required_bool(cancelling, "cancelled", at="blocked cancellation response")
    assert (
        required_text(cancelling, "status", at="blocked cancellation response")
        == "cancelling"
    )

    cancelled = wait_for_run_status(
        lambda: thread_state(service_stack, run_id), _is_cancelled, timeout=30.0
    )
    service_stack.record(f"blocked-cancelled:{run_id}", cancelled)
    assert (
        required_text(cancelled, "status", at="blocked cancellation state")
        == "cancelled"
    )


def test_pre_ingest_deterministic_cancellation_settles_terminally(
    service_stack: ServiceStack,
) -> None:
    """A real cancel accepted immediately after start survives ingest startup."""
    workspace = service_stack.runtime_dir / "pre-ingest-cancellation"
    workspace.mkdir(parents=True, exist_ok=True)
    workspace_root = str(Path(workspace))
    run_id = f"pre-ingest-cancel-{uuid4().hex}"
    with service_stack.gateway_client(timeout=30.0) as client:
        started = client.post(
            "/v1/runs",
            json={
                "run_id": run_id,
                "message": "Cancel before the deterministic ingest begins.",
                "team_preset": "deterministic-cancel-window",
                "selection": fetch_in_process_selection(client, workspace_root),
                "metadata": {"workspace_root": workspace_root},
                "autonomous": True,
            },
        )
        started.raise_for_status()
        created = json_object(started.json(), at="pre-ingest cancellation run start")
    assert (
        required_text(created, "run_id", at="pre-ingest cancellation run start")
        == run_id
    )

    cancelling = json_object(
        service_stack.cancel_thread(run_id), at="pre-ingest cancellation response"
    )
    assert required_bool(cancelling, "cancelled", at="pre-ingest cancellation response")
    assert (
        required_text(cancelling, "status", at="pre-ingest cancellation response")
        == "cancelling"
    )

    cancelled = wait_for_run_status(
        lambda: thread_state(service_stack, run_id), _is_cancelled, timeout=30.0
    )
    service_stack.record(f"pre-ingest-cancelled:{run_id}", cancelled)
    assert (
        required_text(cancelled, "status", at="pre-ingest cancellation state")
        == "cancelled"
    )
