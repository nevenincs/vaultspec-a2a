"""Permission/resume certification against the real compose stack."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


def test_permission_request_can_be_resumed_via_public_api(
    service_stack: ServiceStack,
) -> None:
    """The human-in-loop preset should pause, resume, and complete."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service permission resume",
    )
    thread_id = created["thread_id"]

    paused = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("pending_permissions"),
    )
    service_stack.record(f"permission-paused:{thread_id}", paused)

    request = paused["pending_permissions"][0]
    response = service_stack.respond_permission(
        request["request_id"],
        option_id=_select_option_id(request, label="approve"),
    )
    assert response["accepted"] is True
    assert response["action_status"] == "accepted_not_applied"
    assert response["applied"] is False

    completed = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
    )
    service_stack.record(f"permission-completed:{thread_id}", completed)

    assert completed["pending_permissions"] == []
    assert completed["status"] == "completed"
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


def test_invalid_permission_option_is_rejected_without_resuming(
    service_stack: ServiceStack,
) -> None:
    """Hostile option ids must keep the thread paused and undispatched."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service permission invalid option",
    )
    thread_id = created["thread_id"]

    paused = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("pending_permissions"),
    )
    request = paused["pending_permissions"][0]

    rejected = service_stack.respond_permission(
        request["request_id"],
        option_id="hostile-option",
        expected_status=409,
    )
    assert rejected["detail"] == "Unknown permission option for this request"

    still_paused = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("pending_permissions"),
    )
    assert still_paused["status"] == paused["status"]
    assert still_paused["pending_permissions"][0]["request_id"] == request["request_id"]


def test_stale_second_permission_response_is_rejected_after_resume(
    service_stack: ServiceStack,
) -> None:
    """A second non-idempotent response must not trigger another resume."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service permission stale response",
    )
    thread_id = created["thread_id"]

    paused = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("pending_permissions"),
    )
    request = paused["pending_permissions"][0]

    approved_option_id = _select_option_id(request, label="approve")
    accepted = service_stack.respond_permission(
        request["request_id"],
        option_id=approved_option_id,
    )
    assert accepted["accepted"] is True

    stale = service_stack.respond_permission(
        request["request_id"],
        option_id=approved_option_id,
        idempotency_key="stale-second-response",
        expected_status=409,
    )
    assert stale["detail"] == "Permission request is no longer pending"

    completed = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
    )
    assistant_messages = [
        message
        for message in completed["messages"]
        if message.get("role") == "assistant"
    ]
    assert assistant_messages[-1]["content"] == (
        "Permission approved. The privileged command completed successfully "
        "and the task is now finished."
    )


def test_permission_deny_option_finishes_with_deterministic_denial(
    service_stack: ServiceStack,
) -> None:
    """The deny branch should remain deterministic under the real stack."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service permission deny response",
    )
    thread_id = created["thread_id"]

    paused = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("pending_permissions"),
    )
    request = paused["pending_permissions"][0]

    denied = service_stack.respond_permission(
        request["request_id"],
        option_id=_select_option_id(request, label="deny"),
    )
    assert denied["accepted"] is True

    completed = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
    )
    assistant_messages = [
        message
        for message in completed["messages"]
        if message.get("role") == "assistant"
    ]
    assert assistant_messages[-1]["content"] == (
        "Permission denied. The privileged command was not executed."
    )


def test_invalid_permission_option_keeps_thread_paused_and_recoverable(
    service_stack: ServiceStack,
) -> None:
    """Invalid permission payloads must fail closed without breaking recovery."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service invalid permission option",
    )
    thread_id = created["thread_id"]

    paused = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("pending_permissions"),
    )
    request = paused["pending_permissions"][0]

    with service_stack.gateway_client(timeout=30.0) as client:
        invalid = client.post(
            f"/api/permissions/{request['request_id']}/respond",
            json={"option_id": "hostile-option"},
        )
    assert invalid.status_code == 409
    assert invalid.json()["detail"] == "Unknown permission option for this request"

    still_paused = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: any(
            permission.get("request_id") == request["request_id"]
            for permission in state.get("pending_permissions", [])
        ),
    )
    assert still_paused["status"] == "input_required"

    resumed = service_stack.respond_permission(
        request["request_id"],
        option_id=_select_option_id(request, label="approve"),
    )
    assert resumed["accepted"] is True
    assert resumed["action_status"] == "accepted_not_applied"

    completed = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
    )
    assistant_messages = [
        message
        for message in completed["messages"]
        if message.get("role") == "assistant"
    ]
    assert assistant_messages[-1]["content"] == (
        "Permission approved. The privileged command completed successfully "
        "and the task is now finished."
    )
