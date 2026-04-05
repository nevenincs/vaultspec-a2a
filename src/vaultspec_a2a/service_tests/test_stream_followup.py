"""SSE and follow-up certification against the real compose stack."""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from .harness import ServiceStack


def _select_option_id(
    request: dict[str, Any],
    *,
    label: str,
) -> str:
    target = label.casefold()
    for option in request.get("options", []):
        option_id = option.get("option_id")
        option_name = option.get("name")
        option_label = option.get("label")
        for candidate in (option_id, option_name, option_label):
            if (
                isinstance(candidate, str)
                and candidate.casefold() == target
                and isinstance(option_id, str)
                and option_id
            ):
                return option_id
    raise AssertionError(f"permission option {label!r} not found: {request}")


def _read_sse_frames(
    response: httpx.Response,
    *,
    stop_when,
    timeout: float = 120.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    events: list[dict[str, Any]] = []
    fields: dict[str, list[str]] = {"data": []}

    def _flush() -> dict[str, Any] | None:
        data_lines = fields.get("data", [])
        if not data_lines:
            fields.clear()
            fields["data"] = []
            return None
        payload = json.loads("\n".join(data_lines))
        fields.clear()
        fields["data"] = []
        return payload

    for raw_line in response.iter_lines():
        if time.monotonic() > deadline:
            break
        if raw_line == "":
            payload = _flush()
            if payload is None:
                continue
            events.append(payload)
            if stop_when(payload):
                return events
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        if key == "data":
            fields.setdefault("data", []).append(value.lstrip())
    raise AssertionError(f"timed out waiting for SSE event; events={events!r}")


def _wait_for_state(
    stack: ServiceStack,
    thread_id: str,
    predicate,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = stack.get_thread_state(thread_id)
        last_state = state
        if predicate(state):
            return state
        time.sleep(1.0)
    raise AssertionError(f"timed out waiting for thread {thread_id}: {last_state}")


def _wait_for_pending_permission(
    stack: ServiceStack,
    thread_id: str,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Wait until a permission pause is fully resumable and durably projected."""

    return _wait_for_state(
        stack,
        thread_id,
        lambda state: (
            state.get("pending_permissions")
            and state.get("status") == "input_required"
            and state.get("execution_readiness") == "paused_resumable"
            and state.get("snapshot_complete") is True
        ),
        timeout=timeout,
    )


def _trigger_after(delay_seconds: float, callback) -> threading.Thread:
    thread = threading.Thread(
        target=lambda: (time.sleep(delay_seconds), callback()),
        daemon=True,
    )
    thread.start()
    return thread


def test_sse_stream_and_followup_message(service_stack: ServiceStack) -> None:
    """Consume SSE for a real run, then verify terminal replay semantics."""
    created = service_stack.create_thread(
        initial_message="Request approval and then continue with a follow-up.",
        team_preset="mock-human-in-loop",
        title="service stream follow-up",
    )
    thread_id = created["thread_id"]

    paused = _wait_for_pending_permission(service_stack, thread_id)
    service_stack.record(f"sse-paused:{thread_id}", paused)

    request = paused["pending_permissions"][0]
    initial_result: dict[str, Any] = {}
    initial_errors: list[BaseException] = []

    def _approve() -> None:
        try:
            initial_result["response"] = service_stack.respond_permission(
                request["request_id"],
                option_id=_select_option_id(request, label="approve"),
            )
        except BaseException as exc:  # pragma: no cover - background thread
            initial_errors.append(exc)

    with (
        service_stack.gateway_client(timeout=None) as client,
        client.stream("GET", f"/api/threads/{thread_id}/stream") as stream,
    ):
        trigger = _trigger_after(0.5, _approve)
        initial_events = _read_sse_frames(
            stream,
            stop_when=lambda event: event.get("type") == "thread_terminal",
        )
        trigger.join(timeout=5.0)

    assert not initial_errors, f"permission approval failed: {initial_errors!r}"
    assert initial_result["response"]["accepted"] is True
    assert initial_result["response"]["action_status"] == "accepted_not_applied"
    assert initial_result["response"]["applied"] is False
    assert any(event.get("type") == "thread_terminal" for event in initial_events)
    assert any(event.get("status") == "completed" for event in initial_events)
    service_stack.record(f"sse-initial:{thread_id}", initial_events)

    completed = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
    )
    service_stack.record(f"sse-completed:{thread_id}", completed)
    assistant_messages = [
        message
        for message in completed["messages"]
        if message.get("role") == "assistant"
    ]
    assert assistant_messages, "resume flow should emit a deterministic assistant reply"
    assert assistant_messages[-1]["content"] == (
        "Permission approved. The privileged command completed successfully "
        "and the task is now finished."
    )

    with (
        service_stack.gateway_client(timeout=None) as client,
        client.stream("GET", f"/api/threads/{thread_id}/stream") as stream,
    ):
        follow_up_events = _read_sse_frames(
            stream,
            stop_when=lambda event: (
                event.get("type") == "thread_terminal"
                and event.get("replay", False)
                and event.get("status") == "completed"
            ),
        )

    assert any(event.get("type") == "thread_terminal" for event in follow_up_events)
    assert follow_up_events[-1].get("status") == "completed"
    assert follow_up_events[-1].get("replay") is True

    final_state = service_stack.get_thread_state(thread_id)
    user_messages = [
        message for message in final_state["messages"] if message["role"] == "user"
    ]
    assert len(user_messages) == 1

    with service_stack.gateway_client(timeout=15.0) as client:
        rejected = client.post(
            f"/api/threads/{thread_id}/messages",
            json={"content": "Continue the same thread with a follow-up request."},
        )

    assert rejected.status_code == 409
    service_stack.record(f"sse-follow-up-rejected:{thread_id}", rejected.json())

    service_stack.record(f"sse-follow-up:{thread_id}", follow_up_events)
    service_stack.record(f"sse-final-state:{thread_id}", final_state)
