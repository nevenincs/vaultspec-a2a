"""Response identity, validation, and state passed through permission handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeIs, cast

from ..database import decode_allowed_options, get_control_action_by_idempotency_key
from ..graph.acp_options import APPROVAL_OPTIONS, valid_option_ids
from ..graph.enums import PermissionType
from ..thread.enums import ApprovalStatus
from ..thread.idempotency import MAX_PERMISSION_ASKS, permission_response_action_key
from ..thread.snapshots import (
    PERMISSION_REQUEST_EVENT_TYPES,
    PLAN_APPROVAL_PAUSE_CAUSES,
)
from ..utils.coercion import coerce_nonempty_str
from .permission_options import answer_is_rejection

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import ControlActionModel, PermissionRequestModel, ThreadModel
    from ..ipc.schemas import DispatchRequest
    from ..thread import CheckpointProjection, ProjectedInterrupt
    from .action_lease import ControlActionClaim

__all__ = [
    "AuthorizedPermission",
    "ParkedPermission",
    "PermissionAsk",
    "PermissionInput",
    "PermissionTransition",
    "RejectedResponse",
    "accepted_answer_option",
    "audited_tool_name",
    "existing_rejection_error",
    "held_interrupt",
    "held_permission_request_ids",
    "journaled_permission_asks",
    "rejected_payload",
    "rejected_permission_error",
    "response_payload",
    "response_verdict",
]


def response_payload(option_id: str, notes: str | None) -> dict[str, object]:
    return {"option_id": option_id, "notes": notes}


@dataclass(frozen=True, slots=True)
class PermissionAsk:
    """One ask of a permission request, and the answer journaled under it.

    ``generation`` is which ask of the request this is, counted from the first.
    ``accepted`` is the response action journaled under it, or ``None`` when the
    ask has no answer yet.
    """

    generation: int
    accepted: ControlActionModel | None


@dataclass(frozen=True, slots=True)
class JournaledAsks:
    """The asks of one permission request, as its journal records them.

    ``unanswered`` is the first ask whose answer has not been applied: either an
    answer still in flight, or - when it carries none - the ask a run holding
    the request again has just made. ``answered`` is the last answer that did
    land, which is what an answer to a request the run is NOT holding is judged
    against.
    """

    unanswered: PermissionAsk
    answered: ControlActionModel | None

    def addressed(self, *, held: bool) -> PermissionAsk:
        """Which ask an answer arriving now is addressed to.

        A run whose checkpoint still holds the request after an earlier answer
        landed has asked it AGAIN, so the answer arriving now belongs to that
        new ask and takes a journal identity of its own. A request the
        checkpoint does not hold has no open ask, so the answer is judged
        against the last one journaled - as the replay, duplicate or
        conflicting second body it is.
        """
        if held or self.unanswered.accepted is not None or self.answered is None:
            return self.unanswered
        return PermissionAsk(self.unanswered.generation - 1, self.answered)


async def journaled_permission_asks(
    db: AsyncSession, *, thread_id: str, request_id: str
) -> JournaledAsks | None:
    """Read every ask of *request_id* the journal records, in order.

    The walk stops at the first ask with no answer, or whose answer has not been
    applied: every ask before it is closed. Nothing here reads which relayed
    frame arrived first - the journal's own settled state is the same whether
    the relay handled a re-ask's park frame before or after the receipt that
    proved the previous answer landed.

    ``None`` says the request has been asked more times than
    :data:`~vaultspec_a2a.thread.idempotency.MAX_PERMISSION_ASKS` keys, which
    the caller refuses rather than reusing an identity and replaying an older
    answer.
    """
    answered: ControlActionModel | None = None
    for generation in range(MAX_PERMISSION_ASKS):
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=permission_response_action_key(request_id, generation),
        )
        if action is None or action.applied_at is None:
            return JournaledAsks(PermissionAsk(generation, action), answered)
        answered = action
    return None


def accepted_answer_option(intent: dict[str, object]) -> str | None:
    """The option the accepted response action froze as the answer given.

    Read beside :func:`response_payload`, which writes it, because the frozen
    envelope of the accepted action is the only record of the answer the
    settlement may act on. The request row's own resolution column is a second
    copy of the same decision and is not read: a row rewritten after
    acceptance - by a tamper or by a writer racing the settlement - must not be
    able to change which option a run is settled under.

    ``None`` means the envelope records no answer at all, which is a payload
    the settlement refuses rather than guesses at.
    """
    return coerce_nonempty_str(intent.get("option_id"))


def _is_json_object(value: object) -> TypeIs[dict[str, object]]:
    """Return whether a decoded JSON value is a string-keyed object."""
    # ``json.loads`` only constructs string-keyed object values; this helper is
    # called only on its decoded result after it has been erased to ``object``.
    return isinstance(value, dict)


@dataclass(frozen=True, slots=True)
class ParkedPermission:
    """The permission or approval request a response answers.

    A request the run's checkpoint holds is ``pending``: its interrupt names its
    type and the options it offers, and nothing the journal cached about it
    decides either. A request the checkpoint no longer holds is read from its
    journal row, which can say what an earlier answer was addressed to so that a
    replay of it is judged the same way, and never that the request is pending.
    """

    request_id: str
    pause_reason_type: str
    tool_call: str | None
    description: str
    offered: list[object]
    pending: bool

    @property
    def option_ids(self) -> set[str]:
        """The option ids a response to this request could name."""
        return valid_option_ids(self.offered)

    @classmethod
    def from_interrupt(
        cls, interrupt: ProjectedInterrupt, *, description: str
    ) -> ParkedPermission:
        """Read a request off the interrupt a checkpoint holds it under.

        *description* is the journal's disclosure copy of the question, which
        the interrupt does not carry.
        """
        offered: list[object]
        tool_call: str | None = None
        if interrupt.interrupt_type in PLAN_APPROVAL_PAUSE_CAUSES:
            offered = [*APPROVAL_OPTIONS]
        else:
            options: object = interrupt.payload.get("options")
            offered = cast("list[object]", options) if isinstance(options, list) else []
            tool_name: object = interrupt.payload.get("tool_name")
            if isinstance(tool_name, str) and tool_name:
                tool_call = tool_name
        return cls(
            request_id=interrupt.interrupt_id,
            pause_reason_type=interrupt.interrupt_type,
            tool_call=tool_call,
            description=description,
            offered=offered,
            pending=True,
        )

    @classmethod
    def from_journal(cls, row: PermissionRequestModel) -> ParkedPermission:
        """Read a request the checkpoint no longer holds from its journal row."""
        return cls(
            request_id=row.request_id,
            pause_reason_type=row.pause_reason_type,
            tool_call=row.tool_call,
            description=row.description,
            offered=decode_allowed_options(row.allowed_options_json) or [],
            pending=False,
        )


def _held_permission_interrupts(
    projection: CheckpointProjection | None,
) -> tuple[ProjectedInterrupt, ...]:
    """Every permission or approval interrupt a checkpoint holds, in its order.

    The plural reading of what a run is parked on, for the decisions that are
    about the whole set rather than about one request: a fan-out stage parks on
    several tool calls at once, and each of them is a question still waiting for
    its own answer. A projection that could not be made holds nothing.
    """
    if projection is None:
        return ()
    return tuple(
        interrupt
        for interrupt in projection.pending_interrupts
        if interrupt.interrupt_type in PERMISSION_REQUEST_EVENT_TYPES
    )


def held_permission_request_ids(
    projection: CheckpointProjection | None,
) -> frozenset[str]:
    """The request ids a checkpoint holds an unanswered permission pause under."""
    return frozenset(
        interrupt.interrupt_id for interrupt in _held_permission_interrupts(projection)
    )


def held_interrupt(
    projection: CheckpointProjection | None, request_id: str
) -> ProjectedInterrupt | None:
    """Return the permission or approval interrupt held under *request_id*.

    The one reading of whether a request is pending: the interrupts a checkpoint
    holds are the questions a run is parked on, so a request not among them is
    not waiting for an answer, whatever the journal says about it. A projection
    that could not be made holds nothing.
    """
    return next(
        (
            interrupt
            for interrupt in _held_permission_interrupts(projection)
            if interrupt.interrupt_id == request_id
        ),
        None,
    )


def response_verdict(permission: ParkedPermission, option_id: str) -> str:
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
    return (
        ApprovalStatus.REJECTED.value
        if answer_is_rejection(permission.offered, option_id)
        else ApprovalStatus.APPROVED.value
    )


def audited_tool_name(permission: ParkedPermission) -> str:
    """Name the gated tool for the audit log, never leaving the column blank.

    An approval pause carries no ``tool_call`` because nothing tool-shaped was
    gated; it resolves to the same ``PLAN_APPROVAL`` sentinel the client-facing
    projection substitutes, so the audit and the surface a reviewer saw agree on
    what was being decided.
    """
    return permission.tool_call or PermissionType.PLAN_APPROVAL.value


def rejected_permission_error(
    permission: ParkedPermission,
    *,
    thread_terminal: bool,
    option_id: str,
) -> tuple[str, int]:
    """Return the protocol-facing error for a rejected permission response."""
    if thread_terminal:
        return ("thread is no longer active", 409)
    if not permission.pending:
        return ("Permission request is no longer pending", 409)
    valid_ids = permission.option_ids
    if not valid_ids:
        return ("Permission request has no valid options", 409)
    if option_id not in valid_ids:
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
    return coerce_nonempty_str(payload.get("error_detail"))


@dataclass(frozen=True, slots=True)
class PermissionInput:
    request_id: str
    option_id: str
    idempotency_key: str | None
    notes: str | None = None


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
    any rejection or dedup outcome is a :class:`ControlActionOutcome` instead.

    ``ask`` is the ask of the request this response answers, resolved once
    inside the write transaction so the dedup read and the claim the transition
    takes can never key on two different asks.
    """

    permission: ParkedPermission
    thread_record: ThreadModel
    thread_id: str
    resolved_idempotency_key: str
    ask: PermissionAsk


@dataclass(frozen=True, slots=True)
class PermissionTransition:
    """The durable state written before dispatch, threaded into dispatch.

    Records the control action and the resume value computed from the option,
    plus the routing fields the resume dispatch carries to the worker.
    """

    claim: ControlActionClaim
    dispatch: DispatchRequest
    approval_status: str | None
