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
- :func:`claim_deletion_saga` stamps a durable ownership marker once.
- :func:`advance_deletion_cleanup_item` records one item's terminal state,
  a no-op when that exact state is already recorded.
- :func:`finalize_deletion_saga` removes the control rows only when every
  manifest item is done, and is a no-op once the saga is gone.

The manifest and per-item result types are the durable representation the saga
persists; the cleanup executor in :mod:`vaultspec_a2a.control.cleanup` consumes
them to perform the real store effects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from ...database import (
    ThreadDeletionSagaModel,
    delete_thread,
    mark_thread_deleting,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CleanupItem",
    "CleanupItemResult",
    "CleanupItemState",
    "CleanupKind",
    "DeletionSaga",
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


class CleanupKind(StrEnum):
    """The store a cleanup item removes state from."""

    CHECKPOINT = "checkpoint"
    ARTIFACT_FILE = "artifact_file"


class CleanupItemState(StrEnum):
    """The terminal-tracking state of one cleanup item.

    ``PENDING`` is the implicit state of an item with no recorded result yet;
    the ledger only ever stores ``DONE`` or ``FAILED``. Finalization requires
    every manifest item to be ``DONE``.
    """

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


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
    """The recorded terminal outcome of one cleanup item."""

    key: str
    state: CleanupItemState
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DeletionSaga:
    """A hydrated view of one durable deletion saga."""

    thread_id: str
    manifest: tuple[CleanupItem, ...]
    results: dict[str, CleanupItemResult]
    claimed: bool
    created: bool


@dataclass(frozen=True, slots=True)
class FinalizeOutcome:
    """The outcome of a finalization attempt."""

    finalized: bool
    already_final: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


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
            }
            for key, result in results.items()
        }
    )


def deserialize_results(raw: str) -> dict[str, CleanupItemResult]:
    """Restore the per-item result ledger from its durable JSON representation."""
    data = json.loads(raw)
    return {
        key: CleanupItemResult(
            key=entry["key"],
            state=CleanupItemState(entry["state"]),
            detail=entry.get("detail"),
        )
        for key, entry in data.items()
    }


def _hydrate(row: ThreadDeletionSagaModel, *, created: bool = False) -> DeletionSaga:
    return DeletionSaga(
        thread_id=row.thread_id,
        manifest=tuple(deserialize_manifest(row.manifest_json)),
        results=deserialize_results(row.result_json),
        claimed=row.claimed_at is not None,
        created=created,
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
    """Claim one deletion saga for a cleanup pass.

    Idempotent: the first claim stamps a durable ownership marker; a repeated
    claim leaves it unchanged and returns the same saga. Returns ``None`` when
    no saga exists (already finalized or never created), so a resumed pass can
    distinguish a completed teardown from an in-flight one.
    """
    row = await session.get(ThreadDeletionSagaModel, thread_id)
    if row is None:
        return None
    if row.claimed_at is None:
        row.claimed_at = _now()
        row.updated_at = _now()
        await session.flush()
    return _hydrate(row)


async def advance_deletion_cleanup_item(
    session: AsyncSession,
    *,
    thread_id: str,
    result: CleanupItemResult,
) -> bool:
    """Advance one cleanup item to its recorded terminal state.

    Idempotent: recording the same state and detail already present is a no-op
    that returns ``False``. A later success can supersede an earlier failure
    (a retry that cleaned the item), and a change of detail is persisted, both
    returning ``True``. Returns ``False`` when no saga exists.

    The row is locked for the read-modify-write. Every item's result lives in
    one serialized blob, so an unlocked read followed by a write is a lost
    update whenever two passes advance concurrently - and two passes ARE
    reachable, because claiming a saga does not exclude a second caller and a
    replayed delete drives its own pass. Losing one item's result is
    unrecoverable rather than merely untidy: the manifest can then never read as
    complete, finalization refuses forever, and the thread stays hidden from
    product reads with its rows intact.

    PARTIAL. This closes the window on the Postgres backend only. SQLAlchemy's
    SQLite dialect silently discards ``FOR UPDATE``, so on the default backend
    two connections can still both read before either writes, and the second
    write still drops the first item's result. Closing it there needs a
    structural change rather than a lock - per-item result rows, so concurrent
    advances touch different rows, or an optimistic version guard on the update
    with a retry. Recorded as an open finding rather than left implied by a
    lock that does not reach the default deployment.
    """
    row = await session.get(ThreadDeletionSagaModel, thread_id, with_for_update=True)
    if row is None:
        return False
    results = deserialize_results(row.result_json)
    prior = results.get(result.key)
    if (
        prior is not None
        and prior.state is result.state
        and prior.detail == result.detail
    ):
        return False
    results[result.key] = result
    row.result_json = serialize_results(results)
    row.updated_at = _now()
    await session.flush()
    return True


async def finalize_deletion_saga(
    session: AsyncSession,
    *,
    thread_id: str,
) -> FinalizeOutcome:
    """Finalize one completed saga by removing its control rows.

    Removes the saga row and then the thread (cascading its remaining control
    rows) only when every manifest item is recorded ``DONE``. Idempotent: a
    saga that no longer exists returns ``finalized=True`` with
    ``already_final=True``; an incomplete saga returns ``finalized=False`` and
    leaves every row in place so the thread stays hidden and resumable.

    Locked for the same reason as the advance: the completeness check and the
    row removal must not straddle a concurrent write, or a pass could read a
    complete manifest while another is still recording an item.
    """
    row = await session.get(ThreadDeletionSagaModel, thread_id, with_for_update=True)
    if row is None:
        return FinalizeOutcome(finalized=True, already_final=True)
    manifest = deserialize_manifest(row.manifest_json)
    results = deserialize_results(row.result_json)
    if not manifest_is_complete(manifest, results):
        return FinalizeOutcome(finalized=False)
    await session.delete(row)
    await session.flush()
    await delete_thread(session, thread_id)
    return FinalizeOutcome(finalized=True)
