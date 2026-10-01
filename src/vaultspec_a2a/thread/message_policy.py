"""Pure message-eligibility logic — no I/O, no database.

Determines whether a follow-up message may be sent to a thread
based on its current status.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .dispatch_policy import FailureType
from .enums import NON_ACTIVE_STATUSES, ThreadStatus

#: The verb and the pause descriptor its caller builds. ``MessageEligibility``
#: is this module's return type and is read through the call rather than
#: imported anywhere, so publishing its name would advertise a surface nothing
#: consumes.
__all__ = ["ParkedPause", "PauseAnswerability", "can_send_followup"]


#: The statuses whose run still owns an unfinished turn and can take a
#: continuation behind it. A follow-up admitted here does NOT take the run's
#: write authority from the turn already executing: it is reserved as a
#: waiting turn and acquires authority only when the executing turn's terminal
#: checkpoint evidence promotes it.
_ADMITTING_STATUSES: frozenset[str] = frozenset(
    {ThreadStatus.SUBMITTED.value, ThreadStatus.RUNNING.value}
)

#: The one occupied status that still refuses. A cancelling run is leaving, so
#: a turn queued behind it would wait for a promotion that can never come.
_CANCELLING_REASON = "Cannot send a follow-up message while the run is cancelling"

#: Where each pause is answered. Spelled out here, in the module that writes
#: the sentence, because a client told only that the run is "paused for input"
#: has to guess which of two verbs clears it - and the wrong guess is this
#: route, which starts a turn and orphans the pause.
_PERMISSION_RESPOND_VERB = "POST /v1/runs/{run_id}/permissions/{request_id}/respond"
_CLARIFICATION_RESPOND_VERB = (
    "POST /v1/runs/{run_id}/clarifications/{request_id}/respond"
)


class PauseAnswerability(StrEnum):
    """Whether the pause a run holds is still waiting for an answer."""

    #: Nobody has answered it; the respond verb below is what clears the run.
    AWAITING_ANSWER = "awaiting_answer"
    #: Answered already, and the worker is applying it. Nothing to send.
    APPLYING_ANSWER = "applying_answer"


@dataclass(frozen=True, slots=True)
class ParkedPause:
    """The pause a parked run is actually holding, read from durable state.

    *permission_request_id* names the outstanding permission request found in
    the journal. ``None`` says the journal holds none, which for a parked run
    means the pause is a clarification interrupt: that one lives in the run's
    checkpoint and is disclosed on run-status, so the refusal sends the caller
    there for its request id rather than inventing one.
    """

    run_id: str
    permission_request_id: str | None = None
    answerability: PauseAnswerability = PauseAnswerability.AWAITING_ANSWER


def _parked_reason(parked_on: ParkedPause | None) -> str:
    """Name the typed respond verb that clears the pause this run holds."""
    if parked_on is None:
        return (
            "Cannot send a follow-up message while the run is paused for input. "
            "Answer the pause through its own typed respond verb; run-status "
            "names the request that is waiting."
        )
    if parked_on.permission_request_id is None:
        verb = _CLARIFICATION_RESPOND_VERB.format(
            run_id=parked_on.run_id, request_id="{request_id}"
        )
        return (
            "Cannot send a follow-up message while the run is paused on a "
            f"clarification. Answer it with {verb}, reading the pending "
            "request id from run-status."
        )
    if parked_on.answerability is PauseAnswerability.APPLYING_ANSWER:
        return (
            "Cannot send a follow-up message while the run is applying the "
            f"answer already given to permission request "
            f"{parked_on.permission_request_id}. The run continues on its own; "
            "nothing needs to be sent."
        )
    verb = _PERMISSION_RESPOND_VERB.format(
        run_id=parked_on.run_id, request_id=parked_on.permission_request_id
    )
    return (
        "Cannot send a follow-up message while the run is paused on a "
        f"permission request. Answer it with {verb}."
    )


@dataclass(frozen=True, slots=True)
class MessageEligibility:
    """Descriptor for whether a follow-up message may be sent.

    ``allowed`` means the run can take the turn as a QUEUED continuation
    behind the one it is running, never as an immediate dispatch: no lifecycle
    state hands a follow-up the run's write authority on arrival.
    """

    allowed: bool
    reason: str | None
    failure_type: FailureType | None = None


def can_send_followup(
    status: str, *, parked_on: ParkedPause | None = None
) -> MessageEligibility:
    """Check whether a thread in the given status may receive a message.

    *parked_on* is the pause a parked run is holding, read from durable state
    by the caller. It narrows the refusal to the one verb that clears this
    run; without it the same ruling is stated generically.
    """
    if status == ThreadStatus.INPUT_REQUIRED.value:
        return MessageEligibility(
            allowed=False,
            reason=_parked_reason(parked_on),
            failure_type=FailureType.INPUT_REQUIRED,
        )
    if status in {
        ThreadStatus.REPAIR_NEEDED.value,
        ThreadStatus.RECONCILING.value,
    }:
        return MessageEligibility(
            allowed=False,
            reason=f"Cannot send messages while thread is in {status!r} repair state",
            failure_type=FailureType.TERMINAL,
        )
    if status in _ADMITTING_STATUSES:
        return MessageEligibility(allowed=True, reason=None)
    if status == ThreadStatus.CANCELLING.value:
        return MessageEligibility(
            allowed=False,
            reason=_CANCELLING_REASON,
            failure_type=FailureType.RUN_BUSY,
        )
    if status in NON_ACTIVE_STATUSES:
        return MessageEligibility(
            allowed=False,
            reason=f"Cannot send messages to thread in {status!r} state",
            failure_type=FailureType.TERMINAL,
        )
    # Deliberately permissive, and deliberately NOT where the admitting states
    # are served: an unclassified status reaching here is indistinguishable
    # from an admitted one, which is exactly what the closed-vocabulary test
    # catches. Classify a new lifecycle state above rather than here.
    return MessageEligibility(allowed=True, reason=None)
