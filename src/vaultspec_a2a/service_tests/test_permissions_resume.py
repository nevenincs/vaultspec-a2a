"""Permission/resume certification against the real compose stack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..testing.payloads import (
    json_object,
    json_object_list,
    required_bool,
    required_text,
)
from ._state import select_option_id, wait_for_state

if TYPE_CHECKING:
    from ..providers._json_contract import JsonObject
    from .harness import ServiceStack


def _pending_permissions(state: JsonObject) -> list[JsonObject]:
    """Read the public pending-permissions projection as real objects."""
    return json_object_list(state.get("pending_permissions"), at="pending permissions")


def _first_pending_permission(state: JsonObject) -> JsonObject:
    """Return the one current permission when the state claims to be paused."""
    pending = _pending_permissions(state)
    assert pending, f"paused thread had no pending permission: {state}"
    return pending[0]


def _messages(state: JsonObject) -> list[JsonObject]:
    """Read the public message projection as real objects."""
    return json_object_list(state.get("messages"), at="thread messages")


def _pending_permission_matching(
    state: JsonObject, description_contains: str
) -> JsonObject:
    """Find the named real pending permission after the state wait established it."""
    needle = description_contains.casefold()
    for permission in _pending_permissions(state):
        description = permission.get("description")
        if isinstance(description, str) and needle in description.casefold():
            return permission
    raise AssertionError(
        f"no pending permission contained {description_contains!r}: {state}"
    )


def _option_ids(permission: JsonObject) -> set[str]:
    """Read the offered permission option identifiers from the real projection."""
    return {
        required_text(option, "option_id", at="permission option")
        for option in json_object_list(
            permission.get("options"), at="permission options"
        )
    }


def _is_completed(state: JsonObject) -> bool:
    """Recognise a durable completed thread state."""
    return state.get("status") == "completed"


def _wait_for_pending_permission(
    stack: ServiceStack,
    thread_id: str,
    *,
    request_id: str | None = None,
    timeout: float = 120.0,
) -> JsonObject:
    """Wait until a permission pause is durably resumable, not just projected."""

    def _matches(state: JsonObject) -> bool:
        pending = _pending_permissions(state)
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

    return wait_for_state(stack, thread_id, _matches, timeout=timeout)


def _wait_for_pending_permission_matching(
    stack: ServiceStack,
    thread_id: str,
    *,
    description_contains: str,
    timeout: float = 120.0,
) -> JsonObject:
    """Wait until the named permission request is durably resumable."""

    needle = description_contains.casefold()

    def _matches(state: JsonObject) -> bool:
        if (
            state.get("status") != "input_required"
            or state.get("execution_readiness") != "paused_resumable"
            or state.get("snapshot_complete") is not True
        ):
            return False
        for permission in _pending_permissions(state):
            description = permission.get("description")
            if isinstance(description, str) and needle in description.casefold():
                return True
        return False

    return wait_for_state(stack, thread_id, _matches, timeout=timeout)


def test_permission_request_can_be_resumed_via_public_api(
    service_stack: ServiceStack,
) -> None:
    """The human-in-loop preset should pause, resume, and complete."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service permission resume",
    )
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    paused = _wait_for_pending_permission(service_stack, thread_id)
    service_stack.record(f"permission-paused:{thread_id}", paused)

    request = _first_pending_permission(paused)
    response = json_object(
        service_stack.respond_permission(
            required_text(request, "request_id", at="pending permission"),
            thread_id=thread_id,
            option_id=select_option_id(request, label="approve"),
        ),
        at="permission response",
    )
    assert required_bool(response, "accepted", at="permission response") is True
    assert (
        required_text(response, "action_status", at="permission response")
        == "accepted_not_applied"
    )
    assert required_bool(response, "applied", at="permission response") is False

    completed = wait_for_state(
        service_stack,
        thread_id,
        _is_completed,
    )
    service_stack.record(f"permission-completed:{thread_id}", completed)

    assert _pending_permissions(completed) == []
    assert completed["status"] == "completed"
    assistant_messages = [
        message
        for message in _messages(completed)
        if message.get("role") == "assistant"
    ]
    assert assistant_messages, "resume flow should emit a deterministic assistant reply"
    assert required_text(assistant_messages[-1], "content", at="assistant message") == (
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
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    paused = _wait_for_pending_permission(service_stack, thread_id)
    request = _first_pending_permission(paused)

    rejected = json_object(
        service_stack.respond_permission(
            required_text(request, "request_id", at="pending permission"),
            thread_id=thread_id,
            option_id="hostile-option",
            expected_status=409,
        ),
        at="rejected permission response",
    )
    assert (
        required_text(rejected, "detail", at="rejected permission response")
        == "Unknown permission option for this request"
    )

    still_paused = _wait_for_pending_permission(
        service_stack,
        thread_id,
        request_id=required_text(request, "request_id", at="pending permission"),
    )
    assert still_paused["status"] == paused["status"]
    assert required_text(
        _first_pending_permission(still_paused),
        "request_id",
        at="still-paused permission",
    ) == required_text(request, "request_id", at="pending permission")


def test_stale_second_permission_response_is_rejected_after_resume(
    service_stack: ServiceStack,
) -> None:
    """A second non-idempotent response must not trigger another resume."""
    created = service_stack.create_thread(
        initial_message="Request approval and then finish the task.",
        team_preset="mock-human-in-loop",
        title="service permission stale response",
    )
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    paused = _wait_for_pending_permission(service_stack, thread_id)
    request = _first_pending_permission(paused)

    approved_option_id = select_option_id(request, label="approve")
    accepted = json_object(
        service_stack.respond_permission(
            required_text(request, "request_id", at="pending permission"),
            thread_id=thread_id,
            option_id=approved_option_id,
        ),
        at="accepted permission response",
    )
    assert (
        required_bool(accepted, "accepted", at="accepted permission response") is True
    )

    stale = json_object(
        service_stack.respond_permission(
            required_text(request, "request_id", at="pending permission"),
            thread_id=thread_id,
            option_id=approved_option_id,
            idempotency_key="stale-second-response",
            expected_status=409,
        ),
        at="stale permission response",
    )
    assert (
        required_text(stale, "detail", at="stale permission response")
        == "Permission request is no longer pending"
    )

    completed = wait_for_state(
        service_stack,
        thread_id,
        _is_completed,
    )
    assistant_messages = [
        message
        for message in _messages(completed)
        if message.get("role") == "assistant"
    ]
    assert required_text(assistant_messages[-1], "content", at="assistant message") == (
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
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    paused = _wait_for_pending_permission(service_stack, thread_id)
    request = _first_pending_permission(paused)
    request_id = required_text(request, "request_id", at="pending permission")

    with service_stack.gateway_client(timeout=30.0) as client:
        invalid = client.post(
            f"/v1/runs/{thread_id}/permissions/{request_id}/respond",
            json={"option_id": "hostile-option"},
        )
    assert invalid.status_code == 409
    assert (
        required_text(
            json_object(invalid.json(), at="invalid permission response"),
            "detail",
            at="invalid permission response",
        )
        == "Unknown permission option for this request"
    )

    _wait_for_pending_permission(
        service_stack,
        thread_id,
        request_id=request_id,
    )

    resumed = json_object(
        service_stack.respond_permission(
            required_text(request, "request_id", at="pending permission"),
            thread_id=thread_id,
            option_id=select_option_id(request, label="approve"),
        ),
        at="resumed permission response",
    )
    assert required_bool(resumed, "accepted", at="resumed permission response") is True
    assert (
        required_text(resumed, "action_status", at="resumed permission response")
        == "accepted_not_applied"
    )

    completed = wait_for_state(
        service_stack,
        thread_id,
        _is_completed,
    )
    assistant_messages = [
        message
        for message in _messages(completed)
        if message.get("role") == "assistant"
    ]
    assert required_text(assistant_messages[-1], "content", at="assistant message") == (
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
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    paused = _wait_for_pending_permission(service_stack, thread_id)
    request = _first_pending_permission(paused)

    denied = json_object(
        service_stack.respond_permission(
            required_text(request, "request_id", at="pending permission"),
            thread_id=thread_id,
            option_id=select_option_id(request, label="deny"),
        ),
        at="denied permission response",
    )
    assert required_bool(denied, "accepted", at="denied permission response") is True
    assert (
        required_text(denied, "action_status", at="denied permission response")
        == "accepted_not_applied"
    )

    completed = wait_for_state(
        service_stack,
        thread_id,
        _is_completed,
    )
    assistant_messages = [
        message
        for message in _messages(completed)
        if message.get("role") == "assistant"
    ]
    assert required_text(assistant_messages[-1], "content", at="assistant message") == (
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
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    plan_paused = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Approve plan for feature",
    )
    service_stack.record(f"supervisor-plan-paused:{thread_id}", plan_paused)

    plan_request = _pending_permission_matching(plan_paused, "Approve plan for feature")
    assert plan_paused["status"] == "input_required"
    assert plan_paused["pause_cause"] == "plan_approval_request"
    assert plan_paused["approval_status"] == "pending"
    assert plan_paused["approval_request_id"] == required_text(
        plan_request, "request_id", at="plan permission"
    )
    assert plan_request["tool_call"] == "plan_approval"
    assert _option_ids(plan_request) == {
        "approve",
        "reject",
    }
    plan_response = json_object(
        service_stack.respond_permission(
            required_text(plan_request, "request_id", at="plan permission"),
            thread_id=thread_id,
            option_id=select_option_id(plan_request, label="approve"),
        ),
        at="plan approval response",
    )
    assert required_bool(plan_response, "accepted", at="plan approval response") is True
    assert (
        required_text(plan_response, "action_status", at="plan approval response")
        == "accepted_not_applied"
    )
    assert (
        required_text(plan_response, "approval_status", at="plan approval response")
        == "approved"
    )

    worker_paused = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Permission required",
    )
    service_stack.record(f"supervisor-worker-paused:{thread_id}", worker_paused)

    worker_request = _pending_permission_matching(worker_paused, "Permission required")
    assert worker_paused["status"] == "input_required"
    assert worker_paused["pause_cause"] == "session_request_permission"
    assert required_text(
        worker_request, "request_id", at="worker permission"
    ) != required_text(plan_request, "request_id", at="plan permission")
    assert worker_request["tool_call"] == "session_request_permission"
    assert _option_ids(worker_request) == {
        "approve",
        "reject_once",
    }
    worker_response = json_object(
        service_stack.respond_permission(
            required_text(worker_request, "request_id", at="worker permission"),
            thread_id=thread_id,
            option_id=select_option_id(worker_request, label="approve"),
        ),
        at="worker approval response",
    )
    assert (
        required_bool(worker_response, "accepted", at="worker approval response")
        is True
    )
    assert (
        required_text(worker_response, "action_status", at="worker approval response")
        == "accepted_not_applied"
    )

    completed = wait_for_state(
        service_stack,
        thread_id,
        _is_completed,
    )
    service_stack.record(f"supervisor-completed:{thread_id}", completed)

    assert _pending_permissions(completed) == []
    assistant_messages = [
        message
        for message in _messages(completed)
        if message.get("role") == "assistant"
    ]
    assert required_text(assistant_messages[-1], "content", at="assistant message") == (
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
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    first_plan_pause = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Approve plan for feature",
    )
    first_request = _pending_permission_matching(
        first_plan_pause, "Approve plan for feature"
    )
    rejected = json_object(
        service_stack.respond_permission(
            required_text(first_request, "request_id", at="first plan permission"),
            thread_id=thread_id,
            option_id=select_option_id(first_request, label="reject"),
        ),
        at="plan rejection response",
    )
    assert required_bool(rejected, "accepted", at="plan rejection response") is True
    assert (
        required_text(rejected, "action_status", at="plan rejection response")
        == "accepted_not_applied"
    )
    assert (
        required_text(rejected, "approval_status", at="plan rejection response")
        == "rejected"
    )

    second_plan_pause = _wait_for_pending_permission_matching(
        service_stack,
        thread_id,
        description_contains="Approve plan for feature",
    )
    service_stack.record(
        f"supervisor-plan-rejected-retry:{thread_id}",
        second_plan_pause,
    )
    second_request = _pending_permission_matching(
        second_plan_pause, "Approve plan for feature"
    )
    assert required_text(
        second_request, "request_id", at="second plan permission"
    ) != required_text(first_request, "request_id", at="first plan permission")
    assert second_plan_pause["pause_cause"] == "plan_approval_request"
    assert second_plan_pause["approval_status"] == "pending"
    assert second_plan_pause["approval_request_id"] == required_text(
        second_request, "request_id", at="second plan permission"
    )
    assert second_request["tool_call"] == "plan_approval"
    assert _option_ids(second_request) == {
        "approve",
        "reject",
    }

    assistant_messages = [
        message
        for message in _messages(second_plan_pause)
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
        for permission in _pending_permissions(second_plan_pause)
    )
