"""Response identity, validation, and state passed through permission handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeIs

from ..graph.enums import PermissionType
from ..thread.enums import ApprovalStatus, PermissionRequestStatus
from ..thread.permission_fsm import response_is_rejection
from .accepted_input import AcceptedActionInput
from .permission_options import extract_allowed_option_ids

if TYPE_CHECKING:
    import httpx

    from ..database import PermissionRequestModel, ThreadModel
    from ..ipc.schemas import DispatchRequest
    from ..thread.dispatch_policy import FailureType
    from .action_lease import ControlActionClaim
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner


_PERMISSION_RESPONSE_KEY_PREFIX = "permission-response:"
_PERMISSION_REJECTION_KEY_PREFIX = "permission-rejection:"


def permission_response_action_key(request_id: str) -> str:
    """Return the single journal identity shared by every client retry."""
    return f"{_PERMISSION_RESPONSE_KEY_PREFIX}{request_id}"


def permission_rejection_action_key(idempotency_key: str) -> str:
    return f"{_PERMISSION_REJECTION_KEY_PREFIX}{idempotency_key}"


def response_payload(option_id: str, notes: str | None) -> dict[str, object]:
    return {"option_id": option_id, "notes": notes}


def action_payload_matches(action: object, option_id: str, notes: str | None) -> bool:
    raw = getattr(action, "payload_json", None)
    if not isinstance(raw, str):
        return False
    try:
        return AcceptedActionInput.model_validate_json(raw).intent == response_payload(
            option_id, notes
        )
    except ValueError:
        return False


def _is_json_object(value: object) -> TypeIs[dict[str, object]]:
    """Return whether a decoded JSON value is a string-keyed object."""
    # ``json.loads`` only constructs string-keyed object values; this helper is
    # called only on its decoded result after it has been erased to ``object``.
    return isinstance(value, dict)


def allowed_option_ids(permission: object) -> set[str]:
    """Extract valid option ids from a durable permission request row."""
    raw_options = getattr(permission, "allowed_options_json", "[]")
    return extract_allowed_option_ids(raw_options)


def response_verdict(permission: object, option_id: str) -> str:
    """Report the decision a response carries without flattening it to pending.

    Reads the verdict from the shared predicate against the options the request
    actually offered, so the status stamped here at submission is the same one the
    ``permission_resolved`` projection recomputes later. Deriving it twice from
    different fields is what previously let the projection overwrite a rejection
    with an approval.

    The thread's approval state and the durable audit log both read the verdict
    from here, for the same reason: two derivations of "was this approved" are
    two chances to disagree about the same decision.
    """
    raw_options = getattr(permission, "allowed_options_json", None)
    return (
        ApprovalStatus.REJECTED.value
        if response_is_rejection(raw_options, option_id)
        else ApprovalStatus.APPROVED.value
    )


def audited_tool_name(permission: PermissionRequestModel) -> str:
    """Name the gated tool for the audit log, never leaving the column blank.

    An approval pause carries no ``tool_call`` because nothing tool-shaped was
    gated; it resolves to the same ``PLAN_APPROVAL`` sentinel the client-facing
    projection substitutes, so the audit and the surface a reviewer saw agree on
    what was being decided.
    """
    return permission.tool_call or PermissionType.PLAN_APPROVAL.value


def rejected_permission_error(
    *,
    permission_status: str | None,
    thread_terminal: bool,
    option_id: str,
    valid_option_ids: set[str],
) -> tuple[str, int]:
    """Return the protocol-facing error for a rejected permission response."""
    if thread_terminal:
        return ("thread is no longer active", 409)
    if permission_status and permission_status != PermissionRequestStatus.PENDING.value:
        return ("Permission request is no longer pending", 409)
    if not valid_option_ids:
        return ("Permission request has no valid options", 409)
    if option_id not in valid_option_ids:
        return ("Unknown permission option for this request", 409)
    return ("Permission response was previously rejected", 409)


def rejected_payload(option_id: str, error_detail: str) -> dict[str, object]:
    """Persist the original rejection reason for idempotent replay."""
    return {"option_id": option_id, "error_detail": error_detail}


def existing_rejection_error(existing_action: object) -> str | None:
    """Read the original rejection reason from a stored control action."""
    raw_payload = getattr(existing_action, "payload_json", None)
    if not isinstance(raw_payload, str) or not raw_payload:
        return None
    try:
        payload: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not _is_json_object(payload):
        return None
    error_detail = payload.get("error_detail")
    return error_detail if isinstance(error_detail, str) and error_detail else None


@dataclass(frozen=True, slots=True)
# Flat outcome fields are mapped directly to the permission response schema.
class PermissionResult:  # pylint: disable=too-many-instance-attributes
    """Outcome of a permission response operation.

    The route handler translates this into an HTTP response or exception.
    """

    request_id: str
    thread_id: str
    accepted: bool
    applied: bool
    action_status: str
    action_id: str | None = None
    idempotency_key: str | None = None
    approval_status: str | None = None
    dispatched: bool = False
    # Error signalling — the route maps these to HTTPException codes.
    error_detail: str | None = None
    error_status_code: int | None = None
    circuit_open: bool = False
    failure_type: FailureType | None = None


@dataclass(frozen=True, slots=True)
class PermissionInput:
    request_id: str
    option_id: str
    idempotency_key: str | None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionRuntime:
    circuit_breaker: WorkerCircuitBreaker
    worker_spawner: LazyWorkerSpawner
    worker_client: httpx.AsyncClient
    recursion_limit: int
    trace_headers: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class RejectedResponse:
    request_id: str
    thread_id: str
    option_id: str
    idempotency_key: str
    approval_status: str | None
    error_detail: str
    error_status_code: int


@dataclass(frozen=True, slots=True)
class AuthorizedPermission:
    """A permission response that cleared every authorization guard.

    Carries the resolved durable state the transition and dispatch stages need,
    so those stages never re-read or re-validate. Produced by
    :func:`_authorize_permission_response` only when the response is admitted;
    any rejection or dedup outcome is a :class:`PermissionResult` instead.
    """

    permission: PermissionRequestModel
    thread_record: ThreadModel
    thread_id: str
    resolved_idempotency_key: str


@dataclass(frozen=True, slots=True)
class PermissionTransition:
    """The durable state written before dispatch, threaded into dispatch.

    Records the control action and the resume value computed from the option,
    plus the routing fields the resume dispatch carries to the worker.
    """

    claim: ControlActionClaim
    dispatch: DispatchRequest
    approval_status: str | None
