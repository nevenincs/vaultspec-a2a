"""SSE and follow-up certification against the real compose stack."""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ..testing.payloads import required_bool, required_text

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from .harness import ServiceStack


_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


def _json_object(value: object, *, at: str) -> dict[str, object]:
    """Narrow one real service payload to an object at the wire boundary."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"expected an object at {at}: {exc}") from exc


def _json_object_list(value: object, *, at: str) -> list[dict[str, object]]:
    """Narrow one real service payload to an object list at the wire boundary."""
    try:
        return _JSON_OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"expected an object list at {at}: {exc}") from exc


def _thread_state(stack: ServiceStack, thread_id: str) -> dict[str, object]:
    """Read the real service state before inspecting its public fields."""
    return _json_object(stack.get_thread_state(thread_id), at="thread state")


def _is_terminal_event(event: dict[str, object]) -> bool:
    """Stop the first real stream only at its terminal event."""
    return event.get("type") == "thread_terminal"


def _is_replayed_terminal_event(event: dict[str, object]) -> bool:
    """Stop the replay stream at the completed terminal replay."""
    return (
        event.get("type") == "thread_terminal"
        and event.get("replay") is True
        and event.get("status") == "completed"
    )


def _is_completed_state(state: dict[str, object]) -> bool:
    """Recognise the final state after the real permission resume."""
    return state.get("status") == "completed"


def _select_option_id(
    request: dict[str, object],
    *,
    label: str,
) -> str:
    target = label.casefold()
    for option in _json_object_list(request.get("options"), at="permission options"):
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
    stop_when: Callable[[dict[str, object]], bool],
    timeout: float = 120.0,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    events: list[dict[str, object]] = []
    fields: dict[str, list[str]] = {"data": []}

    def _flush() -> dict[str, object] | None:
        data_lines = fields.get("data", [])
        if not data_lines:
            fields.clear()
            fields["data"] = []
            return None
        decoded: object = json.loads("\n".join(data_lines))
        payload = _json_object(decoded, at="SSE frame")
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
    predicate: Callable[[dict[str, object]], bool],
    *,
    timeout: float = 120.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        state = _thread_state(stack, thread_id)
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
) -> dict[str, object]:
    """Wait until a permission pause is fully resumable and durably projected."""

    def _is_resumable_permission(state: dict[str, object]) -> bool:
        return (
            bool(state.get("pending_permissions"))
            and state.get("status") == "input_required"
            and state.get("execution_readiness") == "paused_resumable"
            and state.get("snapshot_complete") is True
        )

    return _wait_for_state(stack, thread_id, _is_resumable_permission, timeout=timeout)


def _trigger_after(
    delay_seconds: float, callback: Callable[[], None]
) -> threading.Thread:
    def _run_after_delay() -> None:
        time.sleep(delay_seconds)
        callback()

    thread = threading.Thread(
        target=_run_after_delay,
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
    created_body = _json_object(created, at="created thread")
    thread_id = required_text(created_body, "run_id", at="created thread")

    paused = _wait_for_pending_permission(service_stack, thread_id)
    service_stack.record(f"sse-paused:{thread_id}", paused)

    pending_permissions = _json_object_list(
        paused.get("pending_permissions"), at="paused thread pending permissions"
    )
    assert pending_permissions, "paused thread had no pending permission"
    request = pending_permissions[0]
    initial_result: dict[str, dict[str, object]] = {}
    initial_errors: list[BaseException] = []

    def _approve() -> None:
        try:
            initial_result["response"] = _json_object(
                service_stack.respond_permission(
                    required_text(request, "request_id", at="pending permission"),
                    thread_id=thread_id,
                    option_id=_select_option_id(request, label="approve"),
                ),
                at="permission response",
            )
        except BaseException as exc:  # pragma: no cover - background thread
            initial_errors.append(exc)

    with (
        service_stack.gateway_client(timeout=None) as client,
        client.stream("GET", f"/v1/runs/{thread_id}/stream") as stream,
    ):
        trigger = _trigger_after(0.5, _approve)
        initial_events = _read_sse_frames(
            stream,
            stop_when=_is_terminal_event,
        )
        trigger.join(timeout=5.0)

    assert not initial_errors, f"permission approval failed: {initial_errors!r}"
    approved = initial_result.get("response")
    assert approved is not None, (
        "permission approval callback did not return a response"
    )
    assert required_bool(approved, "accepted", at="permission response") is True
    assert (
        required_text(approved, "action_status", at="permission response")
        == "accepted_not_applied"
    )
    assert required_bool(approved, "applied", at="permission response") is False
    assert any(event.get("type") == "thread_terminal" for event in initial_events)
    assert any(event.get("status") == "completed" for event in initial_events)
    service_stack.record(f"sse-initial:{thread_id}", initial_events)

    completed = _wait_for_state(
        service_stack,
        thread_id,
        _is_completed_state,
    )
    service_stack.record(f"sse-completed:{thread_id}", completed)
    assistant_messages = [
        message
        for message in _json_object_list(
            completed.get("messages"), at="completed messages"
        )
        if message.get("role") == "assistant"
    ]
    assert assistant_messages, "resume flow should emit a deterministic assistant reply"
    assert required_text(assistant_messages[-1], "content", at="assistant message") == (
        "Permission approved. The privileged command completed successfully "
        "and the task is now finished."
    )

    with (
        service_stack.gateway_client(timeout=None) as client,
        client.stream("GET", f"/v1/runs/{thread_id}/stream") as stream,
    ):
        follow_up_events = _read_sse_frames(
            stream,
            stop_when=_is_replayed_terminal_event,
        )

    assert any(event.get("type") == "thread_terminal" for event in follow_up_events)
    assert follow_up_events[-1].get("status") == "completed"
    assert (
        required_bool(follow_up_events[-1], "replay", at="terminal replay frame")
        is True
    )

    final_state = _thread_state(service_stack, thread_id)
    user_messages = [
        message
        for message in _json_object_list(
            final_state.get("messages"), at="final messages"
        )
        if required_text(message, "role", at="final message") == "user"
    ]
    assert len(user_messages) == 1

    with service_stack.gateway_client(timeout=15.0) as client:
        rejected = client.post(
            f"/v1/runs/{thread_id}/messages",
            json={"content": "Continue the same thread with a follow-up request."},
        )

    assert rejected.status_code == 409
    service_stack.record(
        f"sse-follow-up-rejected:{thread_id}",
        _json_object(rejected.json(), at="rejected follow-up response"),
    )

    service_stack.record(f"sse-follow-up:{thread_id}", follow_up_events)
    service_stack.record(f"sse-final-state:{thread_id}", final_state)
