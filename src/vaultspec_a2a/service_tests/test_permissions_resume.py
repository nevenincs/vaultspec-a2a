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


def _wait_for_pending_permission(
    stack: ServiceStack,
    thread_id: str,
    *,
    request_id: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Wait until a permission pause is durably resumable, not just projected."""

    def _matches(state: dict[str, Any]) -> bool:
        pending = state.get("pending_permissions", [])
        if not pending:
            return False
        if request_id is not None and not any(
            permission.get("request_id") == request_id for permission in pending
        ):
            return False
        return (
            state.get("status") == "input_required"
            and state.get("execution_readiness") == "paused_resumable"
            and state.get("snapshot_complete") is True
        )

    return _wait_for_state(stack, thread_id, _matches, timeout=timeout)


def _wait_for_pending_permission_matching(
    stack: ServiceStack,
    thread_id: str,
    *,
    description_contains: str,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Wait until the named permission request is durably resumable."""

    needle = description_contains.casefold()

    def _matches(state: dict[str, Any]) -> bool:
        if (
            state.get("status") != "input_required"
            or state.get("execution_readiness") != "paused_resumable"
            or state.get("snapshot_complete") is not True
        ):
            return False
        for permission in state.get("pending_permissions", []):
            description = permission.get("description")
            if isinstance(description, str) and needle in description.casefold():
                return True
        return False

    return _wait_for_state(stack, thread_id, _matches, timeout=timeout)


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

    paused = _wait_for_pending_permission(service_stack, thread_id)
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

    paused = _wait_for_pending_permission(service_stack, thread_id)
    request = paused["pending_permissions"][0]

    rejected = service_stack.respond_permission(
        request["request_id"],
        option_id="hostile-option",
        expected_status=409,
    )
    assert rejected["detail"] == "Unknown permission option for this request"

    still_paused = _wait_for_pending_permission(
        service_stack,
        thread_id,
        request_id=request["request_id"],
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

    paused = _wait_for_pending_permission(service_stack, thread_id)
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

    paused = _wait_for_pending_permission(service_stack, thread_id)
    request = paused["pending_permissions"][0]

    with service_stack.gateway_client(timeout=30.0) as client:
        invalid = client.post(
            f"/api/permissions/{request['request_id']}/respond",
            json={"option_id": "hostile-option"},
        )
    assert invalid.status_code == 409
    assert invalid.json()["detail"] == "Unknown permission option for this request"

    _wait_for_pending_permission(
        service_stack,
        thread_id,
        request_id=request["request_id"],
    )

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


def test_permission_denial_completes_with_denied_outcome(
    service_stack: ServiceStack,
) -> None:
    """The deny path should remain deterministic and avoid privileged work."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service permission deny",
    )
    thread_id = created["thread_id"]

    paused = _wait_for_pending_permission(service_stack, thread_id)
    request = paused["pending_permissions"][0]

    denied = service_stack.respond_permission(
        request["request_id"],
        option_id=_select_option_id(request, label="deny"),
    )
    assert denied["accepted"] is True
    assert denied["action_status"] == "accepted_not_applied"

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


def test_supervisor_plan_approval_pause_can_resume_through_real_stack(
    service_stack: ServiceStack,
) -> None:
    """Supervisor approval and worker approval must both remain controllable."""
    workspace_root = service_stack.runtime_dir / "supervisor-plan-workspace"
    plan_dir = workspace_root / ".vault" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "audit-five-plan.md").write_text(
        "# Audit 5 Plan\n\nExecute the approved implementation path.\n",
        encoding="utf-8",
    )

    created = service_stack.create_thread(
        initial_message="Implement the approved feature through the supervisor path.",
        team_preset="mock-supervisor-human-in-loop",
        title="service supervisor approval resume",
        metadata={
            "workspace_root": str(workspace_root),
            "feature_tag": "audit-five",
        },
    )
    thread_id = created["thread_id"]

    plan_paused = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Approve plan for feature",
    )
    service_stack.record(f"supervisor-plan-paused:{thread_id}", plan_paused)

    plan_request = next(
        permission
        for permission in plan_paused["pending_permissions"]
        if "Approve plan for feature" in str(permission.get("description", ""))
    )
    assert plan_paused["status"] == "input_required"
    assert plan_paused["pause_cause"] == "plan_approval_request"
    assert plan_paused["approval_status"] == "pending"
    assert plan_paused["approval_request_id"] == plan_request["request_id"]
    assert plan_request["tool_call"] == "plan_approval"
    assert {option["option_id"] for option in plan_request.get("options", [])} == {
        "approve",
        "reject",
    }
    plan_response = service_stack.respond_permission(
        plan_request["request_id"],
        option_id=_select_option_id(plan_request, label="approve"),
    )
    assert plan_response["accepted"] is True
    assert plan_response["action_status"] == "accepted_not_applied"

    worker_paused = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Permission required",
    )
    service_stack.record(f"supervisor-worker-paused:{thread_id}", worker_paused)

    worker_request = next(
        permission
        for permission in worker_paused["pending_permissions"]
        if "Permission required" in str(permission.get("description", ""))
    )
    assert worker_paused["status"] == "input_required"
    assert worker_paused["pause_cause"] == "session_request_permission"
    assert worker_request["request_id"] != plan_request["request_id"]
    assert worker_request["tool_call"] == "session_request_permission"
    assert {option["option_id"] for option in worker_request.get("options", [])} == {
        "approve",
        "reject_once",
    }
    worker_response = service_stack.respond_permission(
        worker_request["request_id"],
        option_id=_select_option_id(worker_request, label="approve"),
    )
    assert worker_response["accepted"] is True
    assert worker_response["action_status"] == "accepted_not_applied"

    completed = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
    )
    service_stack.record(f"supervisor-completed:{thread_id}", completed)

    assert completed["pending_permissions"] == []
    assistant_messages = [
        message
        for message in completed["messages"]
        if message.get("role") == "assistant"
    ]
    assert assistant_messages[-1]["content"] == (
        "Permission approved. The privileged command completed successfully "
        "and the task is now finished."
    )


def test_supervisor_plan_rejection_requires_revision_before_reapproval(
    service_stack: ServiceStack,
) -> None:
    """Supervisor rejection should revise first, then require a fresh approval."""
    feature_tag = "audit-five-reject"
    workspace_root = service_stack.runtime_dir / "supervisor-plan-reject-workspace"
    plan_dir = workspace_root / ".vault" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / f"{feature_tag}-plan.md").write_text(
        "# Audit 5 Plan\n\nExecute the approved implementation path.\n",
        encoding="utf-8",
    )

    created = service_stack.create_thread(
        initial_message="Implement the approved feature through the supervisor path.",
        team_preset="mock-supervisor-human-in-loop",
        title="service supervisor reject revise",
        metadata={
            "workspace_root": str(workspace_root),
            "feature_tag": feature_tag,
        },
    )
    thread_id = created["thread_id"]

    first_plan_pause = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Approve plan for feature",
    )
    first_request = next(
        permission
        for permission in first_plan_pause["pending_permissions"]
        if "Approve plan for feature" in str(permission.get("description", ""))
    )
    rejected = service_stack.respond_permission(
        first_request["request_id"],
        option_id=_select_option_id(first_request, label="reject"),
    )
    assert rejected["accepted"] is True
    assert rejected["action_status"] == "accepted_not_applied"

    second_plan_pause = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Approve plan for feature",
    )
    service_stack.record(
        f"supervisor-plan-rejected-retry:{thread_id}",
        second_plan_pause,
    )
    second_request = next(
        permission
        for permission in second_plan_pause["pending_permissions"]
        if "Approve plan for feature" in str(permission.get("description", ""))
    )
    assert second_request["request_id"] != first_request["request_id"]
    assert second_plan_pause["pause_cause"] == "plan_approval_request"
    assert second_plan_pause["approval_status"] == "pending"
    assert second_plan_pause["approval_request_id"] == second_request["request_id"]
    assert second_request["tool_call"] == "plan_approval"
    assert {option["option_id"] for option in second_request.get("options", [])} == {
        "approve",
        "reject",
    }

    assistant_messages = [
        message
        for message in second_plan_pause["messages"]
        if message.get("role") == "assistant"
    ]
    assert any(
        message.get("content")
        == (
            "Revising the implementation plan based on the rejection feedback "
            "before asking for approval again."
        )
        for message in assistant_messages
    )
    assert not any(
        permission.get("tool_call") == "session_request_permission"
        for permission in second_plan_pause["pending_permissions"]
    )
