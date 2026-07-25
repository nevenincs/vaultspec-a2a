"""Idempotent repository for the cross-store thread deletion saga.

A thread delete spans three stores that cannot be committed atomically: the
LangGraph checkpoint store, the workspace filesystem, and the control database.
The saga makes that removal failure-atomic by writing a durable manifest of
cleanup work before any irreversible effect, then advancing per-item results
until every item is done, and only then removing the control rows.

Every operation here is idempotent so a replayed delete request, a crash-and-
resume, or a duplicated cleanup pass converges on one saga and one outcome:

- :func:`create_deletion_saga` creates exactly one saga and transitions the
  thread to ``deleting``, or returns the existing saga unchanged.
- :func:`claim_deletion_saga` grants exclusive ownership of the cleanup pass to
  one caller at a time, refusing a second pass while the claim is live.
- :func:`advance_deletion_cleanup_item` records one item's terminal state,
  a no-op when that exact state is already recorded.
- :func:`finalize_deletion_saga` removes the control rows only when every
  manifest item is settled, and is a no-op once the saga is gone.

Idempotency alone is not liveness, and two liveness properties are enforced
here because their absence ends the same way - a thread hidden from product
reads with its rows intact, forever:

- **Exclusion, not just marking.** The claim is a conditional update, so
  concurrent delete requests cannot both drive the manifest. A pass that ends
  without finalizing releases its claim, and a lease returns a saga held by a
  pass that died mid-teardown, so exclusion never becomes its own wedge.
- **Bounded failure.** An item that fails is retried across passes only up to
  :data:`_MAX_CLEANUP_ATTEMPTS`, after which it is recorded ``ABANDONED`` and
  stops blocking finalization. A cleanup target that can never be removed - a
  file held open, a revoked permission, a detached volume - then costs a leaked
  external object, recorded and logged, instead of an undeletable thread.

The manifest and per-item result types are the durable representation the saga
persists; the cleanup executor in :mod:`vaultspec_a2a.control.cleanup` consumes
them to perform the real store effects.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from ...database import (
    ThreadDeletionSagaModel,
    delete_thread,
    mark_thread_deleting,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy import CursorResult, Result
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CleanupItem",
    "CleanupItemResult",
    "CleanupItemState",
    "CleanupKind",
    "DeletionSaga",
    "DeletionSagaContentionError",
    "FinalizeOutcome",
    "advance_deletion_cleanup_item",
    "claim_deletion_saga",
    "create_deletion_saga",
    "deserialize_manifest",
    "deserialize_results",
    "finalize_deletion_saga",
    "manifest_is_complete",
    "serialize_manifest",
    "serialize_results",
]

logger = logging.getLogger(__name__)

_CLAIM_LEASE = timedelta(minutes=5)
"""How long a claim survives a pass that never released it.

A pass that ends normally releases its claim when finalization refuses, so this
lease only ever covers a pass killed mid-teardown. A cleanup pass deletes a
checkpoint and unlinks a handful of files - seconds of work - so five minutes is
a wide margin over a healthy pass while still returning a saga abandoned by a
dead process to the next delete request.
"""

_MAX_CLEANUP_ATTEMPTS = 3
"""Recorded failures after which a cleanup item is abandoned rather than retried.

Two retries across separate delete requests cover the transient causes - a file
briefly held open, a checkpoint store restarting. Beyond that the failure is
treated as permanent, because continuing to refuse finalization trades a leaked
external object for a thread that can never be deleted.
"""

_MAX_ADVANCE_ATTEMPTS = 8
"""Compare-and-swap retries before an advance reports contention.

Each retry re-reads the ledger and rebuilds the write, so a retry is only ever
consumed by a genuine concurrent writer. Exhausting them means sustained
contention on one saga, which is not a state the saga can silently absorb: a
dropped result is unrecoverable.
"""


class DeletionSagaContentionError(RuntimeError):
    """Raised when a cleanup result cannot be recorded under sustained contention.

    Recording a result is not optional - a dropped result leaves a manifest that
    can never read as settled - so exhausting the compare-and-swap retries is
    surfaced rather than swallowed.
    """


class CleanupKind(StrEnum):
    """The store a cleanup item removes state from."""

    CHECKPOINT = "checkpoint"
    ARTIFACT_FILE = "artifact_file"


class CleanupItemState(StrEnum):
    """The terminal-tracking state of one cleanup item.

    ``PENDING`` is the implicit state of an item with no recorded result yet;
    the ledger stores ``DONE``, ``FAILED``, or ``ABANDONED``.

    ``FAILED`` is retryable: the next pass attempts the item again, and a later
    success supersedes it. ``ABANDONED`` is the terminal failure a retryable
    failure becomes once it has been recorded :data:`_MAX_CLEANUP_ATTEMPTS`
    times - the item is treated as permanently unremovable and stops blocking
    finalization, so the saga's liveness does not depend on a store that will
    never cooperate. Finalization requires every item to be ``DONE`` or
    ``ABANDONED``.
    """

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class CleanupItem:
    """One immutable unit of cross-store cleanup captured in the manifest.

    ``key`` is the stable identity used to record and look up the item's
    result. ``target`` is the checkpoint thread id or the resolved artifact
    file path. ``root`` is the workspace root an artifact file must remain
    contained within, and is ``None`` for checkpoint items.
    """

    kind: CleanupKind
    key: str
    target: str
    root: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupItemResult:
    """The recorded outcome of one cleanup item.

    ``attempts`` counts how many times a failure has been recorded for this
    item across every pass; it is owned by the ledger, so a caller reporting a
    result leaves it at its default and
    :func:`advance_deletion_cleanup_item` supplies the durable count.
    """

    key: str
    state: CleanupItemState
    detail: str | None = None
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class DeletionSaga:
    """A hydrated view of one durable deletion saga.

    ``claimed`` reports that a durable ownership marker exists - which says
    nothing about who holds it. ``owned`` reports that *this* call holds the
    claim and is the only field a caller may drive the manifest on: a hydrated
    saga with ``owned`` false belongs to another live pass and must not be
    executed.
    """

    thread_id: str
    manifest: tuple[CleanupItem, ...]
    results: dict[str, CleanupItemResult]
    claimed: bool
    created: bool
    owned: bool = False


@dataclass(frozen=True, slots=True)
class FinalizeOutcome:
    """The outcome of a finalization attempt.

    ``abandoned`` carries the items that were finalized as permanently
    unremovable rather than cleaned, so the caller can report - and an operator
    can see - that the control rows went away while some external state did
    not.
    """

    finalized: bool
    already_final: bool = False
    abandoned: tuple[CleanupItemResult, ...] = ()


def _now() -> datetime:
    return datetime.now(UTC)


def _rows_matched(result: Result[Any]) -> int:
    """Return how many rows a conditional write matched.

    Both conditional writes here decide on the match count, and a DML execution
    always yields a cursor result; only the declared return type of
    ``Session.execute`` is the wider ``Result``.
    """
    return cast("CursorResult[Any]", result).rowcount


def serialize_manifest(items: Sequence[CleanupItem]) -> str:
    """Serialize a cleanup manifest to its durable JSON representation."""
    return json.dumps(
        [
            {
                "kind": item.kind.value,
                "key": item.key,
                "target": item.target,
                "root": item.root,
            }
            for item in items
        ]
    )


def deserialize_manifest(raw: str) -> list[CleanupItem]:
    """Restore a cleanup manifest from its durable JSON representation."""
    data = json.loads(raw)
    return [
        CleanupItem(
            kind=CleanupKind(entry["kind"]),
            key=entry["key"],
            target=entry["target"],
            root=entry.get("root"),
        )
        for entry in data
    ]


def serialize_results(results: Mapping[str, CleanupItemResult]) -> str:
    """Serialize the per-item result ledger to its durable JSON representation."""
    return json.dumps(
        {
            key: {
                "key": result.key,
                "state": result.state.value,
                "detail": result.detail,
                "attempts": result.attempts,
            }
            for key, result in results.items()
        }
    )


def deserialize_results(raw: str) -> dict[str, CleanupItemResult]:
    """Restore the per-item result ledger from its durable JSON representation.

    ``attempts`` defaults to zero so a ledger written before the attempt count
    existed restores without a migration and simply starts counting from its
    next recorded failure.
    """
    data = json.loads(raw)
    return {
        key: CleanupItemResult(
            key=entry["key"],
            state=CleanupItemState(entry["state"]),
            detail=entry.get("detail"),
            attempts=entry.get("attempts", 0),
        )
        for key, entry in data.items()
    }


def _hydrate(
    row: ThreadDeletionSagaModel,
    *,
    created: bool = False,
    owned: bool = False,
) -> DeletionSaga:
    return DeletionSaga(
        thread_id=row.thread_id,
        manifest=tuple(deserialize_manifest(row.manifest_json)),
        results=deserialize_results(row.result_json),
        claimed=row.claimed_at is not None,
        created=created,
        owned=owned,
    )


def manifest_is_complete(
    manifest: Sequence[CleanupItem],
    results: Mapping[str, CleanupItemResult],
) -> bool:
    """Return whether every manifest item has a recorded ``DONE`` result."""
    for item in manifest:
        result = results.get(item.key)
        if result is None or result.state is not CleanupItemState.DONE:
            return False
    return True


def _abandoned_items(
    manifest: Sequence[CleanupItem],
    results: Mapping[str, CleanupItemResult],
) -> tuple[CleanupItemResult, ...] | None:
    """Return the abandoned items of a settled manifest, or ``None`` if unsettled.

    A manifest is settled once every item is either ``DONE`` or ``ABANDONED``.
    An item still pending, or failed but below the attempt ceiling, leaves work
    a later pass can still complete, so the manifest is not settled and
    finalization must keep refusing.
    """
    if manifest_is_complete(manifest, results):
        return ()
    abandoned: list[CleanupItemResult] = []
    for item in manifest:
        result = results.get(item.key)
        if result is None:
            return None
        if result.state is CleanupItemState.ABANDONED:
            abandoned.append(result)
        elif result.state is not CleanupItemState.DONE:
            return None
    return tuple(abandoned)


def _record_for(
    prior: CleanupItemResult | None,
    result: CleanupItemResult,
) -> CleanupItemResult | None:
    """Return the ledger entry a reported result produces, or ``None`` for a no-op.

    A success is recorded once and supersedes any earlier failure, so a retry
    that finally cleans an item - including one already abandoned - restores it
    to ``DONE``. A failure always changes the ledger because it advances the
    attempt count, and reaching :data:`_MAX_CLEANUP_ATTEMPTS` promotes the item
    to the terminal ``ABANDONED`` state.
    """
    if result.state is CleanupItemState.DONE:
        if (
            prior is not None
            and prior.state is CleanupItemState.DONE
            and prior.detail == result.detail
        ):
            return None
        return CleanupItemResult(
            key=result.key,
            state=CleanupItemState.DONE,
            detail=result.detail,
            attempts=prior.attempts if prior is not None else 0,
        )

    failures = (CleanupItemState.FAILED, CleanupItemState.ABANDONED)
    prior_attempts = (
        prior.attempts if prior is not None and prior.state in failures else 0
    )
    attempts = prior_attempts + 1
    state = (
        CleanupItemState.ABANDONED
        if attempts >= _MAX_CLEANUP_ATTEMPTS
        else CleanupItemState.FAILED
    )
    return CleanupItemResult(
        key=result.key,
        state=state,
        detail=result.detail,
        attempts=attempts,
    )


async def create_deletion_saga(
    session: AsyncSession,
    *,
    thread_id: str,
    manifest: Sequence[CleanupItem],
) -> DeletionSaga:
    """Create one deletion saga and transition the thread to ``deleting``.

    Idempotent: when a saga already exists for the thread the captured manifest
    is authoritative and is returned unchanged (``created=False``), so a
    replayed delete request always resumes the same saga rather than starting a
    second teardown or recapturing a manifest against already-cleaned state.

    The manifest row is written and the thread marked ``deleting`` before the
    caller commits, so the first durable fact of a delete is the control state,
    not an irreversible external effect.
    """
    existing = await session.get(ThreadDeletionSagaModel, thread_id)
    if existing is not None:
        return _hydrate(existing, created=False)

    row = ThreadDeletionSagaModel(
        thread_id=thread_id,
        manifest_json=serialize_manifest(manifest),
        result_json=serialize_results({}),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent request created the saga between the read and the insert.
        # Discard this transaction's pending work and resume the winner's saga.
        await session.rollback()
        existing = await session.get(ThreadDeletionSagaModel, thread_id)
        if existing is None:
            raise
        return _hydrate(existing, created=False)

    await mark_thread_deleting(session, thread_id)
    await session.flush()
    return _hydrate(row, created=True)


async def claim_deletion_saga(
    session: AsyncSession,
    *,
    thread_id: str,
) -> DeletionSaga | None:
    """Claim exclusive ownership of one deletion saga for a cleanup pass.

    Returns ``None`` when no saga exists (already finalized or never created),
    so a resumed pass can distinguish a completed teardown from an in-flight
    one. Otherwise returns the hydrated saga with ``owned`` reporting whether
    this call won the claim; a caller must drive the manifest only when it did.

    Exclusion is the point. The claim is a single conditional update, so of two
    concurrent delete requests exactly one row is matched and exactly one caller
    is told it owns the saga. Both passes executing would be more than redundant
    work: each takes its result snapshot at claim time, and the second pass's
    ledger write - built from a read taken before the first pass recorded its
    item - would drop that item permanently, leaving a manifest that can never
    settle and a thread that can never finalize.

    The claim is leased rather than permanent. A pass killed mid-teardown would
    otherwise hold the saga for the life of the deployment, which is the same
    wedge exclusion exists to prevent; after :data:`_CLAIM_LEASE` the saga is
    claimable again and the next delete request resumes it.
    """
    now = _now()
    claim = await session.execute(
        update(ThreadDeletionSagaModel)
        .where(
            ThreadDeletionSagaModel.thread_id == thread_id,
            or_(
                ThreadDeletionSagaModel.claimed_at.is_(None),
                ThreadDeletionSagaModel.claimed_at < now - _CLAIM_LEASE,
            ),
        )
        .values(claimed_at=now, updated_at=now)
        .execution_options(synchronize_session="fetch")
    )
    row = await session.get(ThreadDeletionSagaModel, thread_id, populate_existing=True)
    if row is None:
        return None
    return _hydrate(row, owned=_rows_matched(claim) == 1)


async def advance_deletion_cleanup_item(
    session: AsyncSession,
    *,
    thread_id: str,
    result: CleanupItemResult,
) -> bool:
    """Advance one cleanup item to its recorded state.

    Recording a success already present is a no-op that returns ``False``. A
    later success supersedes an earlier failure (a retry that cleaned the item)
    and a recorded failure advances the item's attempt count, both returning
    ``True``. Returns ``False`` when no saga exists.

    Every item's result lives in one serialized blob, so a plain read followed
    by a write is a lost update whenever two passes advance concurrently, and
    losing one item's result is unrecoverable rather than untidy: the manifest
    can then never settle, finalization refuses forever, and the thread stays
    hidden from product reads with its rows intact. The write is therefore a
    compare-and-swap - the update matches only while the ledger still holds the
    exact bytes this call read - so a write built on a stale read is rejected
    and rebuilt rather than applied over a concurrent one.

    Compare-and-swap rather than a row lock because the lock does not reach the
    default backend: SQLAlchemy's SQLite dialect silently discards ``FOR
    UPDATE``. The select still takes the lock where the backend honours it, so
    on Postgres contention serialises instead of retrying, but correctness rests
    on the swap, which holds on both.
    """
    for _ in range(_MAX_ADVANCE_ATTEMPTS):
        witnessed = (
            await session.execute(
                select(ThreadDeletionSagaModel.result_json)
                .where(ThreadDeletionSagaModel.thread_id == thread_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if witnessed is None:
            return False
        results = deserialize_results(witnessed)
        record = _record_for(results.get(result.key), result)
        if record is None:
            return False
        results[record.key] = record
        now = _now()
        swap = await session.execute(
            update(ThreadDeletionSagaModel)
            .where(
                ThreadDeletionSagaModel.thread_id == thread_id,
                ThreadDeletionSagaModel.result_json == witnessed,
            )
            .values(result_json=serialize_results(results), updated_at=now)
            .execution_options(synchronize_session="fetch")
        )
        if _rows_matched(swap) == 1:
            return True
        # Another pass rewrote the ledger between the read and the write. Its
        # result must survive, so this one is rebuilt on the ledger it left.
        logger.debug(
            "Deletion cleanup advance for thread %s item %s lost a swap; retrying",
            thread_id,
            result.key,
        )
    msg = (
        f"Could not record cleanup result {result.key!r} for thread "
        f"{thread_id!r} after {_MAX_ADVANCE_ATTEMPTS} attempts"
    )
    raise DeletionSagaContentionError(msg)


async def finalize_deletion_saga(
    session: AsyncSession,
    *,
    thread_id: str,
) -> FinalizeOutcome:
    """Finalize one settled saga by removing its control rows.

    Removes the saga row and then the thread (cascading its remaining control
    rows) only when every manifest item is settled - recorded ``DONE``, or
    ``ABANDONED`` after exhausting its attempts. Idempotent: a saga that no
    longer exists returns ``finalized=True`` with ``already_final=True``; an
    unsettled saga returns ``finalized=False`` and leaves every row in place so
    the thread stays hidden and resumable.

    A refusal also releases the claim, because refusing is how a pass ends
    without finishing. The lease exists for passes that die without reaching
    here; a pass that does reach it has stopped, so holding its claim until the
    lease expired would stall the next delete request for no reason. Callers
    must therefore own the saga before finalizing it - this is the terminal step
    of a claimed pass, not a free-standing probe.

    Finalizing over abandoned items is deliberate. Requiring every item to be
    ``DONE`` makes one permanently unremovable target - a file held open, a
    revoked permission, a detached volume - hide the thread from product reads
    for the life of the deployment with no operator escape. The abandonment is
    logged and returned rather than swallowed, so the leaked external state is
    visible instead of the thread being undeletable.

    Locked for the same reason as the advance: the settlement check and the row
    removal must not straddle a concurrent write, or a pass could read a settled
    manifest while another is still recording an item.
    """
    row = await session.get(ThreadDeletionSagaModel, thread_id, with_for_update=True)
    if row is None:
        return FinalizeOutcome(finalized=True, already_final=True)
    manifest = deserialize_manifest(row.manifest_json)
    results = deserialize_results(row.result_json)
    abandoned = _abandoned_items(manifest, results)
    if abandoned is None:
        row.claimed_at = None
        row.updated_at = _now()
        await session.flush()
        return FinalizeOutcome(finalized=False)
    if abandoned:
        logger.error(
            "Finalizing deletion saga for thread %s with %d unremovable "
            "cleanup item(s); external state is leaked: %s",
            thread_id,
            len(abandoned),
            "; ".join(f"{item.key}: {item.detail}" for item in abandoned),
        )
    await session.delete(row)
    await session.flush()
    await delete_thread(session, thread_id)
    return FinalizeOutcome(finalized=True, abandoned=abandoned)
