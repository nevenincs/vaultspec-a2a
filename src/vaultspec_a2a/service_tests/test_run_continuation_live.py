"""Certify queued turns across a real gateway, worker, and checkpoint store."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ..control.accepted_input import AcceptedActionInput, restore_accepted_dispatch
from ..testing import wait_for_run_status
from ..testing.payloads import json_object, json_object_list
from ..testing.sse import read_frames_until
from ..thread.action_receipts import GraphActionReceipt
from ._state import thread_state
from .harness import build_service_stack

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ..conftest import ExternalPrerequisiteRule
    from .harness import ServiceStack


async def _wait_for_completed_checkpoint(path: Path, run_id: str) -> None:
    """Observe the real worker's durable turn evidence while the gateway is down."""
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        await saver.setup()
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            stored = await saver.aget_tuple(
                {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}
            )
            if stored is not None:
                values = stored.checkpoint.get("channel_values", {})
                if values.get("graph_completion_receipts"):
                    return
            await asyncio.sleep(0.2)
    raise AssertionError(f"worker did not commit completed checkpoint for {run_id}")


def _wait_for_postgres_completed_checkpoint(url: str, run_id: str) -> None:
    with PostgresSaver.from_conn_string(url) as saver:
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            stored = saver.get_tuple(
                {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}
            )
            if stored is not None:
                values = stored.checkpoint.get("channel_values", {})
                if values.get("graph_completion_receipts"):
                    return
            time.sleep(0.2)
    raise AssertionError(f"worker did not commit completed checkpoint for {run_id}")


@pytest.fixture(scope="session")
def postgres_service_stack(
    external_prerequisite: ExternalPrerequisiteRule,
) -> Iterator[ServiceStack]:
    external_prerequisite("docker")
    external_prerequisite("postgres")
    stack = build_service_stack(
        postgres_url=os.environ["VAULTSPEC_A2A_TEST_POSTGRES_URL"]
    )
    try:
        stack.start()
        yield stack
    finally:
        stack.stop()


def _replay_events(stack: ServiceStack, run_id: str) -> list[tuple[int, str]]:
    query = (
        "SELECT sequence, event_type FROM run_events "
        "WHERE thread_id = :run_id ORDER BY sequence"
    )
    if stack.postgres_url is None:
        with sqlite3.connect(stack.runtime_dir / "service.db") as connection:
            return connection.execute(
                query.replace(":run_id", "?"), (run_id,)
            ).fetchall()
    url = make_url(stack.postgres_url).set(drivername="postgresql+psycopg")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return [
                (int(sequence), str(event_type))
                for sequence, event_type in connection.execute(
                    text(query), {"run_id": run_id}
                )
            ]
    finally:
        engine.dispose()


def _queued_action_state(
    stack: ServiceStack, run_id: str, action_id: str
) -> tuple[str, str | None]:
    query = (
        "SELECT result_status, graph_receipt_json FROM control_actions "
        "WHERE thread_id = :run_id AND id = :action_id"
    )
    parameters = {"run_id": run_id, "action_id": action_id}
    if stack.postgres_url is None:
        with sqlite3.connect(stack.runtime_dir / "service.db") as connection:
            row = connection.execute(
                query.replace(":run_id", "?").replace(":action_id", "?"),
                (run_id, action_id),
            ).fetchone()
    else:
        url = make_url(stack.postgres_url).set(drivername="postgresql+psycopg")
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                row = connection.execute(text(query), parameters).one_or_none()
        finally:
            engine.dispose()
    assert row is not None
    return str(row[0]), str(row[1]) if row[1] is not None else None


def _accepted_ingest(
    stack: ServiceStack, run_id: str
) -> tuple[AcceptedActionInput, GraphActionReceipt, str]:
    query = (
        "SELECT payload_json, graph_receipt_json, dispatch_id "
        "FROM control_actions WHERE thread_id = :run_id AND action_type = 'ingest'"
    )
    if stack.postgres_url is None:
        with sqlite3.connect(stack.runtime_dir / "service.db") as connection:
            row = connection.execute(
                query.replace(":run_id", "?"), (run_id,)
            ).fetchone()
    else:
        url = make_url(stack.postgres_url).set(drivername="postgresql+psycopg")
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                row = connection.execute(text(query), {"run_id": run_id}).one_or_none()
        finally:
            engine.dispose()
    assert row is not None
    payload, receipt, dispatch_id = row
    assert payload is not None and receipt is not None and dispatch_id is not None
    return (
        AcceptedActionInput.model_validate(json.loads(payload)),
        GraphActionReceipt.model_validate_json(receipt),
        str(dispatch_id),
    )


@pytest.mark.requires_prerequisites("docker")
def _assert_queued_turn_runs_after_a_live_turn_with_one_terminal(
    stack: ServiceStack,
) -> None:
    created = stack.create_thread(
        initial_message="Complete this turn before the next one.",
        team_preset="deterministic-supervisor-routing",
        autonomous=True,
    )
    run_id = str(created["run_id"])
    message_path = f"/v1/runs/{run_id}/messages"
    with stack.gateway_client(timeout=30.0) as client:
        queued = client.post(
            message_path,
            json={"content": "Now complete the second turn."},
            headers={"Idempotency-Key": f"{run_id}-followup"},
        )
        assert queued.status_code == 202, queued.text
        queued_body = json_object(queued.json(), at="queued continuation")
        assert queued_body["action_status"] == "queued"
        assert queued_body["queue_position"] == 1

        replay = client.post(
            message_path,
            json={"content": "Now complete the second turn."},
            headers={"Idempotency-Key": f"{run_id}-followup"},
        )
        assert replay.status_code == 202, replay.text
        assert replay.json()["action_id"] == queued_body["action_id"]
        assert replay.json()["queue_position"] == 1

        changed = client.post(
            message_path,
            json={"content": "A different second turn."},
            headers={"Idempotency-Key": f"{run_id}-followup"},
        )
        assert changed.status_code == 409, changed.text
        assert changed.json()["detail"]["code"] == "conflict"

        full = client.post(
            message_path,
            json={"content": "A third turn should not queue."},
            headers={"Idempotency-Key": f"{run_id}-third"},
        )
        assert full.status_code == 409, full.text
        assert full.json()["detail"]["code"] == "queue_full"

    completed = wait_for_run_status(
        lambda: thread_state(stack, run_id),
        lambda state: state.get("status") == "completed",
    )
    assert completed["status"] == "completed"
    assert completed["repair_status"] != "needs_reconciliation"
    user_messages = [
        message
        for message in json_object_list(completed["messages"], at="run messages")
        if message.get("role") == "user"
    ]
    assert [message["content"] for message in user_messages] == [
        "Complete this turn before the next one.",
        "Now complete the second turn.",
    ]

    with (
        stack.gateway_client(timeout=None) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as stream,
    ):
        frames = read_frames_until(
            stream.iter_lines(),
            lambda event: event.get("type") == "thread_terminal",
            timeout=120.0,
        )
    terminal_frames = [
        frame for frame in frames if frame.get("type") == "thread_terminal"
    ]
    assert len(terminal_frames) == 1
    assert terminal_frames[0]["status"] == "completed"

    events = _replay_events(stack, run_id)
    assert events
    assert [sequence for sequence, _event_type in events] == list(
        range(1, len(events) + 1)
    )
    assert sum(event_type == "thread_terminal" for _sequence, event_type in events) == 1


@pytest.mark.requires_prerequisites("docker")
def test_queued_turn_runs_after_a_live_turn_with_one_terminal(
    service_stack: ServiceStack,
) -> None:
    _assert_queued_turn_runs_after_a_live_turn_with_one_terminal(service_stack)


@pytest.mark.requires_prerequisites("docker", "postgres")
def test_postgres_queued_turn_runs_after_a_live_turn_with_one_terminal(
    postgres_service_stack: ServiceStack,
) -> None:
    _assert_queued_turn_runs_after_a_live_turn_with_one_terminal(postgres_service_stack)


def _assert_admission_at_the_worker_completion_boundary_has_one_outcome(
    stack: ServiceStack,
) -> None:
    created = stack.create_thread(
        initial_message="Finish the first turn near admission.",
        team_preset="deterministic-supervisor-routing",
        autonomous=True,
    )
    run_id = str(created["run_id"])
    if stack.postgres_url is None:
        asyncio.run(
            _wait_for_completed_checkpoint(stack.runtime_dir / "service.db", run_id)
        )
    else:
        _wait_for_postgres_completed_checkpoint(stack.postgres_url, run_id)

    with stack.gateway_client(timeout=30.0) as client:
        admission = client.post(
            f"/v1/runs/{run_id}/messages",
            json={"content": "A turn submitted at completion."},
            headers={"Idempotency-Key": f"{run_id}-boundary"},
        )

    assert admission.status_code in (202, 409), admission.text
    if admission.status_code == 202:
        assert admission.json()["action_status"] == "queued"
    else:
        assert admission.json()["detail"]["code"] == "terminal"

    completed = wait_for_run_status(
        lambda: thread_state(stack, run_id),
        lambda state: state.get("status") == "completed",
        timeout=180.0,
    )
    users = [
        message
        for message in json_object_list(completed["messages"], at="boundary run")
        if message.get("role") == "user"
    ]
    assert len(users) == (2 if admission.status_code == 202 else 1)
    assert completed["repair_status"] != "needs_reconciliation"


@pytest.mark.requires_prerequisites("docker")
def test_admission_at_the_worker_completion_boundary_has_one_outcome(
    service_stack: ServiceStack,
) -> None:
    _assert_admission_at_the_worker_completion_boundary_has_one_outcome(service_stack)


@pytest.mark.requires_prerequisites("docker", "postgres")
def test_postgres_admission_at_the_worker_completion_boundary_has_one_outcome(
    postgres_service_stack: ServiceStack,
) -> None:
    _assert_admission_at_the_worker_completion_boundary_has_one_outcome(
        postgres_service_stack
    )


def _assert_busy_worker_retains_the_accepted_run(stack: ServiceStack) -> None:
    stack.catalog_selection(str(stack.runtime_dir), "mock-success-multi")
    stack.pause_mock_service()
    try:
        created = stack.create_thread(
            initial_message="Complete the accepted turn after the busy probe.",
            team_preset="mock-success-multi",
            autonomous=True,
        )
        run_id = str(created["run_id"])
        accepted, receipt, dispatch_id = _accepted_ingest(stack, run_id)
        probe_id = f"{run_id}-busy-probe"
        probe = restore_accepted_dispatch(accepted, dispatch_id=probe_id).model_copy(
            update={
                "graph_action_receipt": receipt.model_copy(
                    update={"dispatch_id": probe_id}
                )
            }
        )
        with stack._worker_client() as worker:
            refused = worker.post("/dispatch", json=probe.model_dump(mode="json"))
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["condition"] == "run_busy"
        assert stack.health()["checks"]["circuit_breaker"]["status"] == "closed"
        original = _queued_action_state(stack, run_id, receipt.action_id)
        assert original[0] in {"accepted_not_applied", "applied"}
        assert original[1] is not None
        assert GraphActionReceipt.model_validate_json(original[1]) == receipt
        assert dispatch_id != probe_id
    finally:
        stack.resume_mock_service()

    completed = wait_for_run_status(
        lambda: thread_state(stack, run_id),
        lambda state: state.get("status") == "completed",
        timeout=180.0,
    )
    assert completed["repair_status"] != "needs_reconciliation"
    users = [
        message
        for message in json_object_list(completed["messages"], at="busy worker run")
        if message.get("role") == "user"
    ]
    assert [message["content"] for message in users] == [
        "Complete the accepted turn after the busy probe."
    ]


@pytest.mark.requires_prerequisites("docker")
def test_real_busy_worker_keeps_its_accepted_run(service_stack: ServiceStack) -> None:
    _assert_busy_worker_retains_the_accepted_run(service_stack)


@pytest.mark.requires_prerequisites("docker", "postgres")
def test_postgres_real_busy_worker_keeps_its_accepted_run(
    postgres_service_stack: ServiceStack,
) -> None:
    _assert_busy_worker_retains_the_accepted_run(postgres_service_stack)


@pytest.mark.requires_prerequisites("docker")
def test_gateway_restart_promotes_queued_turn_once(
    service_stack: ServiceStack,
) -> None:
    service_stack.catalog_selection(
        str(service_stack.runtime_dir), "mock-success-multi"
    )
    service_stack.pause_mock_service()
    try:
        created = service_stack.create_thread(
            initial_message="Finish this turn while the gateway restarts.",
            team_preset="mock-success-multi",
            autonomous=True,
        )
        run_id = str(created["run_id"])
        with service_stack.gateway_client(timeout=30.0) as client:
            queued = client.post(
                f"/v1/runs/{run_id}/messages",
                json={"content": "Finish the accepted continuation."},
                headers={"Idempotency-Key": f"{run_id}-restart-followup"},
            )
        assert queued.status_code == 202, queued.text
        service_stack.crash_gateway()
    finally:
        service_stack.resume_mock_service()
    asyncio.run(
        _wait_for_completed_checkpoint(service_stack.runtime_dir / "service.db", run_id)
    )
    assert _queued_action_state(
        service_stack, run_id, str(queued.json()["action_id"])
    ) == ("queued", None)
    service_stack.restart_gateway()

    completed = wait_for_run_status(
        lambda: thread_state(service_stack, run_id),
        lambda state: state.get("status") == "completed",
        timeout=180.0,
    )
    assert completed["repair_status"] != "needs_reconciliation"
    users = [
        message
        for message in json_object_list(completed["messages"], at="recovered run")
        if message.get("role") == "user"
    ]
    assert [message["content"] for message in users] == [
        "Finish this turn while the gateway restarts.",
        "Finish the accepted continuation.",
    ]
    assert (
        sum(
            event_type == "thread_terminal"
            for _sequence, event_type in _replay_events(service_stack, run_id)
        )
        == 1
    )


@pytest.mark.requires_prerequisites("docker", "postgres")
def test_postgres_gateway_restart_promotes_queued_turn_once(
    postgres_service_stack: ServiceStack,
) -> None:
    stack = postgres_service_stack
    stack.catalog_selection(str(stack.runtime_dir), "mock-success-multi")
    stack.pause_mock_service()
    try:
        created = stack.create_thread(
            initial_message="Finish this PostgreSQL turn while the gateway restarts.",
            team_preset="mock-success-multi",
            autonomous=True,
        )
        run_id = str(created["run_id"])
        with stack.gateway_client(timeout=30.0) as client:
            queued = client.post(
                f"/v1/runs/{run_id}/messages",
                json={"content": "Finish the accepted PostgreSQL continuation."},
                headers={"Idempotency-Key": f"{run_id}-postgres-restart"},
            )
        assert queued.status_code == 202, queued.text
        stack.crash_gateway()
    finally:
        stack.resume_mock_service()
    assert stack.postgres_url is not None
    _wait_for_postgres_completed_checkpoint(stack.postgres_url, run_id)
    assert _queued_action_state(stack, run_id, str(queued.json()["action_id"])) == (
        "queued",
        None,
    )
    stack.restart_gateway()

    completed = wait_for_run_status(
        lambda: thread_state(stack, run_id),
        lambda state: state.get("status") == "completed",
        timeout=180.0,
    )
    assert completed["repair_status"] != "needs_reconciliation"
    users = [
        message
        for message in json_object_list(
            completed["messages"], at="PostgreSQL recovered run"
        )
        if message.get("role") == "user"
    ]
    assert [message["content"] for message in users] == [
        "Finish this PostgreSQL turn while the gateway restarts.",
        "Finish the accepted PostgreSQL continuation.",
    ]
    assert (
        sum(
            event_type == "thread_terminal"
            for _sequence, event_type in _replay_events(stack, run_id)
        )
        == 1
    )
