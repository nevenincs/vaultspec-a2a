"""Settle a run's proven terminal inside the transaction that elects it.

Completion, failure and cancellation end a run from different evidence, but
ending a run writes the same things every time: the elected status, the
stream position the run reached, an answer for every continuation still
waiting, the expiry of any pending permission, a cleared approval, the
settled action marked applied, and repair returned to healthy. They are
written in one place so that no terminal can leave a run half-settled, holding
a pause or a queued turn that nothing will ever resume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from ..database import (
    ThreadStatusElectionOutcome,
    begin_write_transaction,
    elect_thread_status,
    expire_pending_permission_requests,
    lock_thread_row,
    mark_control_action_applied,
    set_thread_approval_state,
)
from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ..thread.repair_policy import terminal_repair_transition
from .continuation_queue import refuse_queued_continuations
from .repair_transitions import apply_repair_transition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import ThreadModel
    from ..thread import ThreadWriteExpectation

__all__ = [
    "TerminalEvidence",
    "lock_terminal_run",
    "settle_terminal",
]

#: Why each terminal refuses the continuations still waiting on its run: a run
#: in any of these states can never promote them.
_QUEUE_REFUSAL_REASONS: Final[dict[ThreadStatus, str]] = {
    ThreadStatus.COMPLETED: "the run completed",
    ThreadStatus.FAILED: "the run's turn failed",
    ThreadStatus.CANCELLED: "the run was cancelled",
}


@dataclass(frozen=True, slots=True)
class TerminalEvidence:
    """The exact action a proven terminal settles, and what settling it records.

    *expectation* is the witness the election compares, snapshotted by the
    caller from the row its proof was checked against. *action_type* and
    *action_receipt_id* name the action the election installs as the run's
    final writer, and *action_id* is that action's journal row. The action is
    marked applied with *result_status*; the failure fields are written only
    by a failed terminal. *queue_refusal_reason* replaces the terminal's own
    account of why the waiting continuations are refused, for a settlement
    that ends the run for a more specific reason.
    """

    expectation: ThreadWriteExpectation
    action_id: str
    action_type: ControlActionType
    action_receipt_id: str
    result_status: ControlActionResultStatus = ControlActionResultStatus.APPLIED
    failure_reason: str | None = None
    provider_condition: str | None = None
    queue_refusal_reason: str | None = None


async def lock_terminal_run(db: AsyncSession, thread_id: str) -> ThreadModel | None:
    """Open a settlement's write transaction and lock the run's own row.

    The write lock comes before any read. A transaction that begins deferred
    and reads first cannot upgrade to a write once another connection has
    committed in between: SQLite refuses it outright instead of waiting. The
    row lock is the one an admission takes, so a continuation offered while
    the run settles either lands first and is answered by the settlement, or
    reads the settled status and is refused there. Without it both could
    commit, stranding the waiting turn on a settled run.
    """
    await begin_write_transaction(db)
    return await lock_thread_row(db, thread_id)


async def settle_terminal(
    db: AsyncSession,
    thread: ThreadModel,
    status: ThreadStatus,
    *,
    evidence: TerminalEvidence,
    last_sequence: int | None,
) -> ThreadStatusElectionOutcome:
    """Elect *status* for the proven action and write what ends the run.

    Runs in the transaction :func:`lock_terminal_run` opened, on the row it
    locked. A lost election writes nothing further. The outcome is returned
    either way, and ending the transaction stays with the caller.
    """
    refusal_reason = _QUEUE_REFUSAL_REASONS[status]
    if evidence.queue_refusal_reason is not None:
        refusal_reason = evidence.queue_refusal_reason
    election = await elect_thread_status(
        db,
        thread.id,
        expectation=evidence.expectation,
        status=status,
        action_type=evidence.action_type,
        action_receipt_id=evidence.action_receipt_id,
        failure_reason=evidence.failure_reason,
        provider_condition=evidence.provider_condition,
    )
    if election.outcome is not ThreadStatusElectionOutcome.WON:
        return election.outcome
    settled_at = datetime.now(UTC)
    if last_sequence is not None:
        thread.last_sequence = last_sequence
    await refuse_queued_continuations(
        db, thread_id=thread.id, refused_at=settled_at, reason=refusal_reason
    )
    await expire_pending_permission_requests(db, thread_id=thread.id)
    await set_thread_approval_state(
        db,
        thread.id,
        approval_status=None,
        approval_request_id=None,
        approval_reason=None,
        approval_response_action_id=None,
    )
    await mark_control_action_applied(
        db,
        evidence.action_id,
        applied_at=settled_at,
        result_status=evidence.result_status,
    )
    await apply_repair_transition(db, thread.id, terminal_repair_transition(status))
    return election.outcome
