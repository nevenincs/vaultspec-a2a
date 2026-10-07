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
from ..thread.enums import ThreadStatus
from ..thread.repair_policy import (
    DISPATCH_FAILED_TRANSITION,
    RepairPhase,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread.repair_policy import RepairTransition

__all__ = [
    "apply_repair_transition",
    "record_failed_permission_resume",
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


async def record_failed_permission_resume(
    db: AsyncSession,
    thread_id: str,
    *,
    reason: str,
) -> ThreadModel | None:
    """Record that a permission resume failed outright and left the run parked.

    An undelivered resume leaves the run parked on its question rather than
    dead, so the status stays ``INPUT_REQUIRED`` and ``failure_reason`` and
    ``provider_condition`` are never written: both describe a run that FAILED,
    and stamping them on a run that is still alive would make a reloading client
    report a failure that never happened. The account lands on the repair
    reason, beside the dispatch-failed transition that hands the run to an
    operator.

    *reason* is the caller's own account of why the dispatch failed; without it a
    client that reloaded would see a quarantined run with no explanation.

    The status moves by election under the run's current writer, from the row as
    this call reads it, because a failed dispatch is a fact about the action that
    owns the run. A run already ``INPUT_REQUIRED`` has nothing to elect, and a
    lost election means a newer writer owns the run, so neither the status nor
    the repair posture of a stale failure is written; ``None`` is returned.
    """
    thread = await get_thread(db, thread_id, refresh=True)
    if thread is None:
        return None
    expectation = thread_write_expectation(thread)
    if expectation.status is not ThreadStatus.INPUT_REQUIRED:
        authority = expectation.authority
        election = await elect_thread_status(
            db,
            thread_id,
            expectation=expectation,
            status=ThreadStatus.INPUT_REQUIRED,
            action_type=authority.action_type,
            action_receipt_id=authority.action_receipt_id,
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
