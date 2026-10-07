"""Apply the repair policy's transitions to a run's durable repair state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import (
    ThreadModel,
    ThreadStatusElectionOutcome,
    elect_thread_status,
    get_thread,
    set_thread_repair_state,
    thread_write_expectation,
)
from ..providers.conditions import ProviderCondition
from ..thread.enums import ThreadStatus
from ..thread.repair_policy import (
    DISPATCH_FAILED_TRANSITION,
    RepairPhase,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread.repair_policy import RepairTransition

__all__ = [
    "apply_dispatch_failure",
    "apply_repair_transition",
    "record_undelivered_dispatch",
]


async def apply_repair_transition(
    db: AsyncSession,
    thread_id: str,
    transition: RepairTransition,
    *,
    reason: str | None = None,
) -> ThreadModel | None:
    """Persist *transition* as the run's repair state.

    Every policy transition reaches the row through here, so the state a
    control-plane event leaves is decided by the policy alone. The repair
    reason is rewritten each time - *reason*, else the transition's own
    account, else nothing - so a transition clears whatever account the last
    one left. The transition's action, when it has one, is recorded as the
    run's last requested or last applied action according to its phase.
    """
    phase = transition.phase
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        repair_reason=reason or transition.reason,
        last_requested_action=(
            transition.action if phase is RepairPhase.REQUESTED else None
        ),
        last_applied_action=transition.action if phase is RepairPhase.APPLIED else None,
    )


async def apply_dispatch_failure(
    db: AsyncSession,
    thread_id: str,
    *,
    failed_status: ThreadStatus,
    reason: str | None = None,
) -> ThreadModel | None:
    """Apply the shared dispatch-failure state transition.

    Run creation, message follow-up, and permission resume all react to a
    should-mark-failed dispatch outcome by pairing a thread-status change with
    the dispatch-failed repair transition. Centralizing the pair keeps a caller
    from updating one without the other.

    ``reason`` is the caller's own account of why the dispatch failed, and every
    caller has one - it was previously spent on an HTTP response body and then
    discarded, so a client that reloaded saw a failed run with no reason at all.

    Where it lands depends on where the run lands, and the distinction is not
    cosmetic. ``failure_reason`` and ``provider_condition`` describe why a run
    FAILED, so they are written only when this transition actually fails it. The
    permission-resume caller passes ``INPUT_REQUIRED``: an undelivered resume
    leaves the run parked on its question rather than dead, and stamping a
    failure reason on a run that is still alive would make a reloading client
    report a failure that never happened. That path carries its account on the
    repair reason instead, which every arm writes.

    The provider condition, when written, is always the floor - a decision rather
    than an omission. A dispatch that never reached the worker engaged no
    provider, so there is none to report; naming one would describe the LOCAL
    worker as though it were the model vendor and send the reader after the wrong
    remedy. The dispatch layer's own failure vocabulary stays in the reason text.

    The status moves by election under the run's current writer, from the row as
    this call reads it, because a failed dispatch is a fact about the action that
    owns the run. A run already in *failed_status* has nothing to elect, and a
    lost election means a newer writer owns the run, so neither the status nor
    the repair posture of a stale failure is written; ``None`` is returned.
    """
    run_actually_failed = failed_status is ThreadStatus.FAILED
    thread = await db.get(ThreadModel, thread_id, populate_existing=True)
    if thread is None:
        return None
    expectation = thread_write_expectation(thread)
    if expectation.status is not failed_status:
        authority = expectation.authority
        election = await elect_thread_status(
            db,
            thread_id,
            expectation=expectation,
            status=failed_status,
            action_type=authority.action_type,
            action_receipt_id=authority.action_receipt_id,
            failure_reason=reason if run_actually_failed else None,
            # The condition rides the FAILURE, not the reason. Gating it on the
            # reason too would let a caller that failed a run without a message
            # persist a failed row with no classification at all - the blank
            # terminal this campaign exists to remove, reintroduced through the
            # back door. A reason is nice to have; a condition is the invariant.
            provider_condition=(
                ProviderCondition.UNKNOWN.value if run_actually_failed else None
            ),
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            return None
    return await apply_repair_transition(
        db, thread_id, DISPATCH_FAILED_TRANSITION, reason=reason
    )


async def record_undelivered_dispatch(
    db: AsyncSession,
    thread_id: str,
    *,
    reason: str,
) -> ThreadModel | None:
    """Record why a control dispatch certainly never reached the worker.

    For the callers whose lease design releases the claim on a definite
    non-delivery: the follow-up or resume did not arrive, but the run itself is
    untouched and still alive. ``failure_reason`` and ``provider_condition`` are
    therefore both off limits here - they are defined as describing a run that
    FAILED, and stamping either would make a reloading client report a failure
    that never happened. The account lands on the repair reason, which is the
    field a still-live run can honestly carry.

    The repair status is left exactly as the caller's pre-dispatch transition
    set it. A released claim stays redrivable, so declaring operator
    intervention here would contradict the very design that released it, and the
    record is self-clearing: every pre-dispatch transition rewrites the repair
    state without a reason, so the next attempt erases the last one's account.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return None
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=thread.repair_status,
        repair_reason=reason,
    )
