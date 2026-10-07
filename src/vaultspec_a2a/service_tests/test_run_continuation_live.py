"""Certify queued turns across a real gateway, worker, and checkpoint store."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..control.accepted_input import AcceptedActionInput, restore_accepted_dispatch
from ..testing import (
    held_turns,
    json_object,
    json_object_list,
    read_frames_until,
    wait_for_run_status,
)
from ..thread.action_receipts import GraphActionReceipt
from ._state import thread_state

if TYPE_CHECKING:
    from pathlib import Path

    from .harness import ServiceStack

# The scenario whose turn stays in flight on the real worker until the test opens
# the stack's hold gate, so a run can be held busy mid-turn across a probe or a
# gateway restart.
_HELD_PRESET = "deterministic-hold-then-complete"


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


def _replay_events(stack: ServiceStack, run_id: str) -> list[tuple[int, str]]:
    with sqlite3.connect(stack.runtime_dir / "service.db") as connection:
        return connection.execute(
            "SELECT sequence, event_type FROM run_events "
            "WHERE thread_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()


def _queued_action_state(
    stack: ServiceStack, run_id: str, action_id: str
) -> tuple[str, str | None]:
    with sqlite3.connect(stack.runtime_dir / "service.db") as connection:
        row = connection.execute(
            "SELECT result_status, graph_receipt_json FROM control_actions "
            "WHERE thread_id = ? AND id = ?",
            (run_id, action_id),
        ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1]) if row[1] is not None else None


def _accepted_ingest(
    stack: ServiceStack, run_id: str
) -> tuple[AcceptedActionInput, GraphActionReceipt, str]:
    with sqlite3.connect(stack.runtime_dir / "service.db") as connection:
        row = connection.execute(
            "SELECT payload_json, graph_receipt_json, dispatch_id "
            "FROM control_actions WHERE thread_id = ? AND action_type = 'ingest'",
            (run_id,),
        ).fetchone()
    assert row is not None
    payload, receipt, dispatch_id = row
    assert payload is not None and receipt is not None and dispatch_id is not None
    return (
        AcceptedActionInput.model_validate(json.loads(payload)),
        GraphActionReceipt.model_validate_json(receipt),
        str(dispatch_id),
    )


@pytest.mark.requires_prerequisites("docker")
def test_queued_turn_runs_after_a_live_turn_with_one_terminal(
    service_stack: ServiceStack,
) -> None:
    created = service_stack.create_thread(
        initial_message="Complete this turn before the next one.",
        team_preset="deterministic-supervisor-routing",
        autonomous=True,
    )
    run_id = str(created["run_id"])
    message_path = f"/v1/runs/{run_id}/messages"
    with service_stack.gateway_client(timeout=30.0) as client:
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
        lambda: thread_state(service_stack, run_id),
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
        service_stack.gateway_client(timeout=None) as client,
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

    events = _replay_events(service_stack, run_id)
    assert events
    assert [sequence for sequence, _event_type in events] == list(
        range(1, len(events) + 1)
    )
    assert sum(event_type == "thread_terminal" for _sequence, event_type in events) == 1


@pytest.mark.requires_prerequisites("docker")
def test_admission_at_the_worker_completion_boundary_has_one_outcome(
    service_stack: ServiceStack,
) -> None:
    created = service_stack.create_thread(
        initial_message="Finish the first turn near admission.",
        team_preset="deterministic-supervisor-routing",
        autonomous=True,
    )
    run_id = str(created["run_id"])
    asyncio.run(
        _wait_for_completed_checkpoint(service_stack.runtime_dir / "service.db", run_id)
    )

    with service_stack.gateway_client(timeout=30.0) as client:
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
        lambda: thread_state(service_stack, run_id),
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
def test_real_busy_worker_keeps_its_accepted_run(service_stack: ServiceStack) -> None:
    with held_turns(service_stack.hold_gate):
        created = service_stack.create_thread(
            initial_message="Complete the accepted turn after the busy probe.",
            team_preset=_HELD_PRESET,
            autonomous=True,
        )
        run_id = str(created["run_id"])
        accepted, receipt, dispatch_id = _accepted_ingest(service_stack, run_id)
        probe_id = f"{run_id}-busy-probe"
        probe = restore_accepted_dispatch(accepted, dispatch_id=probe_id).model_copy(
            update={
                "graph_action_receipt": receipt.model_copy(
                    update={"dispatch_id": probe_id}
                )
            }
        )
        with service_stack._worker_client() as worker:
            refused = worker.post("/dispatch", json=probe.model_dump(mode="json"))
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["condition"] == "run_busy"
        assert service_stack.health()["checks"]["circuit_breaker"]["status"] == "closed"
        original = _queued_action_state(service_stack, run_id, receipt.action_id)
        assert original[0] in {"accepted_not_applied", "applied"}
        assert original[1] is not None
        assert GraphActionReceipt.model_validate_json(original[1]) == receipt
        assert dispatch_id != probe_id

    completed = wait_for_run_status(
        lambda: thread_state(service_stack, run_id),
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
def test_gateway_restart_promotes_queued_turn_once(
    service_stack: ServiceStack,
) -> None:
    with held_turns(service_stack.hold_gate):
        created = service_stack.create_thread(
            initial_message="Finish this turn while the gateway restarts.",
            team_preset=_HELD_PRESET,
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
