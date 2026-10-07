"""Consolidated dispatch-to-worker orchestration.

Single entry point for all gateway-to-worker dispatch calls.  Handles
the common core: ensure worker is spawned, circuit breaker check,
HTTP POST to ``/dispatch``, and success/failure recording.

Protocol-agnostic: does NOT raise ``HTTPException``.  Callers are
responsible for translating errors into HTTP or WebSocket responses.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx

from ..database import (
    ThreadStatusElectionOutcome,
    begin_write_transaction,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_session_factory,
    list_threads,
    thread_write_expectation,
)
from ..ipc.schemas import (
    DispatchRequest,
    DispatchResponse,
)
from ..thread.dispatch_policy import FailureType
from ..thread.enums import ThreadStatus
from ..utils.coercion import coerce_object_mapping
from ._thread_metadata import workspace_root_from_metadata
from .accepted_input import AcceptedActionInput, restore_accepted_dispatch
from .dispatch_receipts import bind_graph_action_receipt
from .execution_authority import ExecutionAuthorityError, resolve_execution_authority
from .workspace import canonical_workspace_root, require_admitted_workspace_root

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import ThreadStatusElectionResult
    from ..database.models import ThreadModel
    from ..providers.team_selection import FrozenLaneAssignment
    from .circuit_breaker import DispatchAdmission, WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "redispatch_reconciling_threads",
    "safe_dispatch",
]

logger = logging.getLogger(__name__)

# Mirrors the worker heartbeat ladder's cadence (worker/ipc.py heartbeat_loop):
# first occurrence logs in full, every Nth repeat thereafter logs in full, the
# rest only advance the counter a batch-end summary reports.
_REDISPATCH_LOG_EVERY_N = 5


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    """Result of a :func:`safe_dispatch` call."""

    success: bool
    failure_type: str | None = None
    exception: Exception | None = None
    detail: str | None = None
    retry_after_seconds: float | None = None
    """How long the worker itself asked the caller to wait, when it said so.

    Present only on a refusal the worker answered with a ``Retry-After``. It is
    the worker's own account of when it expects to have room, which is better
    information than a blind backoff curve, so a scheduler takes the later of
    the two rather than retrying into a wall it was told about.
    """


class DispatchError(Exception):
    """Base class for dispatch failures."""


class IncompatibleDispatchAuthorityError(DispatchError):
    """Current durable graph-action evidence is absent or inconsistent."""


class WorkerCircuitOpenError(DispatchError):
    """Raised when the circuit breaker is open and rejects the dispatch."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class WorkerAtCapacityError(DispatchError):
    """Raised when the worker returns HTTP 429 (too many requests)."""

    def __init__(
        self,
        thread_id: str,
        dispatch_id: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.dispatch_id = dispatch_id
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Worker at capacity (429) for dispatch_id={dispatch_id} thread {thread_id}"
        )


class WorkerDispatchRejectedError(DispatchError):
    """Raised when the worker returns a non-2xx response (e.g. 500, 503)."""

    def __init__(
        self,
        thread_id: str,
        dispatch_id: str,
        status_code: int,
        body: str,
        condition: str | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.dispatch_id = dispatch_id
        self.status_code = status_code
        self.body = body
        self.condition = condition
        super().__init__(
            f"Worker rejected dispatch_id={dispatch_id} thread {thread_id}"
            f" with status {status_code}"
        )


class WorkerUnreachableError(DispatchError):
    """Raised when the worker cannot be reached (httpx transport error)."""

    def __init__(
        self,
        thread_id: str,
        dispatch_id: str,
        cause: httpx.HTTPError,
    ) -> None:
        self.thread_id = thread_id
        self.dispatch_id = dispatch_id
        self.cause = cause
        super().__init__(
            f"Worker unreachable for dispatch_id={dispatch_id} thread {thread_id}"
        )


async def dispatch_to_worker(
    worker_client: httpx.AsyncClient,
    dispatch: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
    spawner: LazyWorkerSpawner,
    *,
    trace_headers: dict[str, str] | None = None,
) -> DispatchResponse:
    """Dispatch a request to the worker process.

    Handles the common dispatch sequence:

    1. Ensure the worker is spawned via ``spawner.ensure_worker()``.
    2. Check that the circuit breaker allows non-cancel dispatches.
    3. HTTP POST to ``/dispatch`` with the serialised payload and optional
       trace propagation headers.
    4. Record success or failure on the circuit breaker.
    5. Return a ``DispatchResponse`` on success.

    Raises:
        WorkerCircuitOpenError: Circuit breaker is open (caller should 503).
        WorkerAtCapacityError: Worker returned 429 (caller decides policy).
        WorkerDispatchRejectedError: Worker returned non-2xx (e.g. 500/503).
        WorkerUnreachableError: httpx transport error (caller decides policy).
    """
    if dispatch.requires_graph_receipt:
        try:
            dispatch.require_graph_action_receipt()
        except ValueError as exc:
            raise IncompatibleDispatchAuthorityError(str(exc)) from exc
    await spawner.ensure_worker()

    # Cancellation bypasses admission but not classification: it must reach a
    # worker the circuit has shut out, and it still reports honestly on whether
    # the transport worked when it got there.
    admission: DispatchAdmission | None = None
    if dispatch.requires_graph_receipt:
        admission = circuit_breaker.pre_dispatch()
        if admission is None:
            raise WorkerCircuitOpenError(circuit_breaker.rejection_detail)

    headers = dict(trace_headers) if trace_headers else {}

    try:
        try:
            resp = await worker_client.post(
                "/dispatch",
                json=dispatch.model_dump(),
                headers=headers or None,
            )
        except httpx.HTTPError as exc:
            circuit_breaker.record_failure()
            logger.warning(
                "Failed to dispatch %s dispatch_id=%s for thread %s",
                dispatch.action,
                dispatch.dispatch_id,
                dispatch.thread_id,
                exc_info=True,
            )
            raise WorkerUnreachableError(
                thread_id=dispatch.thread_id,
                dispatch_id=dispatch.dispatch_id,
                cause=exc,
            ) from exc

        return _dispatch_response_or_raise(resp, dispatch, circuit_breaker)
    finally:
        # Every arm above settles the breaker, so this only matters for an
        # attempt abandoned without one - a cancellation, or a fault in this
        # function. An unreturned probe would leave the half-open circuit
        # admitting nothing until the process restarted. The breaker takes this
        # dispatch's own admission, so an attempt that outlived a transition
        # into half-open returns nothing rather than another request's probe.
        if admission is not None:
            circuit_breaker.release_probe(admission)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Read a ``Retry-After`` delay the worker stated in seconds.

    Only the delta-seconds form is honoured. The HTTP-date form is legal but the
    worker never sends it, and parsing a date against a clock this process does
    not share would turn a hint into a wrong answer.
    """
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _refusal_condition(resp: httpx.Response) -> str | None:
    """Read the typed condition the worker named for a refusal, if any."""
    try:
        body = coerce_object_mapping(resp.json())
    except ValueError:
        return None
    if body is None:
        return None
    detail = coerce_object_mapping(body.get("detail"))
    if detail is None:
        return None
    condition = detail.get("condition")
    return condition if isinstance(condition, str) else None


def _dispatch_response_or_raise(
    resp: httpx.Response,
    dispatch: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
) -> DispatchResponse:
    """Classify the worker's HTTP response and update circuit health.

    Only an unreachable worker and a worker that failed inside itself are
    transport health. A refusal the worker composed and returned - capacity, or
    a request it will not serve - proves the opposite, so it settles the breaker
    as healthy and leaves the retry decision to the caller's own policy.
    """
    if resp.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        circuit_breaker.record_refusal()
        logger.warning(
            "Worker at capacity (429) for dispatch_id=%s thread %s",
            dispatch.dispatch_id,
            dispatch.thread_id,
        )
        raise WorkerAtCapacityError(
            thread_id=dispatch.thread_id,
            dispatch_id=dispatch.dispatch_id,
            retry_after_seconds=_retry_after_seconds(resp),
        )

    if resp.is_server_error:
        circuit_breaker.record_failure()
        logger.warning(
            "Worker failed dispatch_id=%s thread %s with status %d",
            dispatch.dispatch_id,
            dispatch.thread_id,
            resp.status_code,
        )
        raise WorkerDispatchRejectedError(
            thread_id=dispatch.thread_id,
            dispatch_id=dispatch.dispatch_id,
            status_code=resp.status_code,
            body=resp.text,
        )

    if not resp.is_success:
        circuit_breaker.record_refusal()
        condition = _refusal_condition(resp)
        logger.warning(
            "Worker refused dispatch_id=%s thread %s with status %d (%s)",
            dispatch.dispatch_id,
            dispatch.thread_id,
            resp.status_code,
            condition or "unclassified",
        )
        raise WorkerDispatchRejectedError(
            thread_id=dispatch.thread_id,
            dispatch_id=dispatch.dispatch_id,
            status_code=resp.status_code,
            body=resp.text,
            condition=condition,
        )

    circuit_breaker.record_success()

    return DispatchResponse(
        status="dispatched",
        thread_id=dispatch.thread_id,
    )


def _log_redispatch_failure_ladder(
    counts: dict[str, int],
    thread_ids: dict[str, list[str]],
    identity: tuple[str, str],
    message: str,
    *args: object,
) -> None:
    """Log a re-dispatch failure at WARNING on the 1st and every Nth repeat.

    A persistent per-thread failure across a large reconciling batch (a stuck
    worker, an open circuit breaker) would otherwise re-log the identical line
    once per thread with no dedup; this mirrors the worker heartbeat ladder
    (first failure -> WARNING, every Nth thereafter -> WARNING, everything
    between only advances the counter). *category* is the failure kind
    (``circuit_open``/``redispatch_error``), so switching kinds mid-batch is a
    state change that always logs at its own occurrence 1. Every occurrence's
    *thread_id* - not just the ones logged in full - is recorded so the
    batch-end summary can name every stuck thread, keeping per-entity
    diagnosability even while the per-occurrence line is suppressed.
    """
    category, thread_id = identity
    counts[category] = counts.get(category, 0) + 1
    thread_ids.setdefault(category, []).append(thread_id)
    n = counts[category]
    if n == 1 or n % _REDISPATCH_LOG_EVERY_N == 0:
        logger.warning(message, *args)


def _reconciling_metadata(thread: ThreadModel) -> dict[str, object]:
    """Read one thread's optional metadata without losing the rest of the sweep."""
    if not thread.thread_metadata:
        return {}
    try:
        raw_metadata: object = json.loads(thread.thread_metadata)
    except json.JSONDecodeError:
        logger.debug("Failed to parse thread metadata for %s", thread.id, exc_info=True)
        return {}
    return coerce_object_mapping(raw_metadata) or {}


async def _refuse_queue_on_settlement(
    db: AsyncSession,
    thread_id: str,
    election: ThreadStatusElectionResult,
    reason: str,
) -> None:
    """Answer a settling run's queue in the transaction that settles it.

    The sweep's per-thread refusals are terminal settlements like any other,
    so a continuation waiting on one would be left on a run that can never
    promote it. Bound to the won election and written before the commit, so a
    lost election refuses nothing: either the run settles and its queue is
    answered, or neither happens.
    """
    from .repositories.continuation_queue import refuse_queued_continuations

    if election.outcome is not ThreadStatusElectionOutcome.WON:
        return
    await refuse_queued_continuations(
        db, thread_id=thread_id, refused_at=datetime.now(UTC), reason=reason
    )


async def _refuse_incompatible_authority(
    db: AsyncSession,
    thread: ThreadModel,
    failure_counts: dict[str, int],
    failure_thread_ids: dict[str, list[str]],
    exc: ExecutionAuthorityError,
) -> None:
    """Fail one incompatible stored run while allowing the sweep to continue."""
    expectation = thread_write_expectation(thread)
    await begin_write_transaction(db)
    election = await elect_thread_status(
        db,
        thread.id,
        expectation=expectation,
        status=ThreadStatus.FAILED,
        action_type=expectation.authority.action_type,
        action_receipt_id=expectation.authority.action_receipt_id,
        failure_reason=(
            f"stored execution authority is incompatible ({exc.reason.value})"
        ),
    )
    await _refuse_queue_on_settlement(
        db, thread.id, election, "the run's stored execution authority is incompatible"
    )
    await db.commit()
    if election.outcome is not ThreadStatusElectionOutcome.WON:
        logger.warning(
            "Skipped stale reconciliation refusal for thread %s: %s",
            thread.id,
            election.outcome.value,
        )
        return
    _log_redispatch_failure_ladder(
        failure_counts,
        failure_thread_ids,
        ("incompatible_execution_authority", thread.id),
        "Refusing incompatible execution authority (%s) for thread %s",
        exc.reason.value,
        thread.id,
    )


async def _refuse_missing_project(
    db: AsyncSession,
    thread: ThreadModel,
    failure_counts: dict[str, int],
    failure_thread_ids: dict[str, list[str]],
) -> None:
    """Fail one run with no active project and keep healthy runs moving."""
    expectation = thread_write_expectation(thread)
    await begin_write_transaction(db)
    election = await elect_thread_status(
        db,
        thread.id,
        expectation=expectation,
        status=ThreadStatus.FAILED,
        action_type=expectation.authority.action_type,
        action_receipt_id=expectation.authority.action_receipt_id,
        failure_reason=(
            "run carries no active project: its stored metadata "
            "names no workspace_root, so it cannot be re-sited"
        ),
    )
    await _refuse_queue_on_settlement(
        db, thread.id, election, "the run carries no active project"
    )
    await db.commit()
    if election.outcome is not ThreadStatusElectionOutcome.WON:
        logger.warning(
            "Skipped stale project refusal for thread %s: %s",
            thread.id,
            election.outcome.value,
        )
        return
    _log_redispatch_failure_ladder(
        failure_counts,
        failure_thread_ids,
        ("no_active_project", thread.id),
        "Refusing to re-dispatch thread %s with no active project",
        thread.id,
    )


async def _restore_reconciling_dispatch(
    db: AsyncSession,
    thread: ThreadModel,
    frozen_map: dict[str, FrozenLaneAssignment],
    workspace_root: str,
) -> DispatchRequest | None:
    """Load the accepted action only when it matches stored execution authority."""
    authority = thread_write_expectation(thread).authority
    action = await get_control_action_by_dispatch_id(
        db,
        thread_id=thread.id,
        dispatch_id=authority.action_receipt_id,
    )
    if action is None or action.payload_json is None:
        logger.warning("No accepted action for reconciling thread %s", thread.id)
        return None
    try:
        accepted = AcceptedActionInput.model_validate_json(action.payload_json)
        dispatch = restore_accepted_dispatch(
            accepted, dispatch_id=authority.action_receipt_id
        )
        if (
            dispatch.model_assignment != frozen_map
            or dispatch.workspace_root is None
            or canonical_workspace_root(
                require_admitted_workspace_root(dispatch.workspace_root)
            )
            != canonical_workspace_root(require_admitted_workspace_root(workspace_root))
        ):
            raise ValueError(
                "accepted execution authority differs from thread metadata"
            )
        return await bind_graph_action_receipt(db, dispatch)
    except ValueError as exc:
        logger.warning("Invalid accepted action for thread %s: %s", thread.id, exc)
        return None


def _log_redispatch_batch_summary(
    failure_counts: dict[str, int], failure_thread_ids: dict[str, list[str]]
) -> None:
    """Summarize repeated failures while retaining every affected thread id."""
    for category, count in failure_counts.items():
        if count > 1:
            logger.info(
                "Re-dispatch failure ladder for %s: %d occurrences this"
                " batch (only the 1st and every %dth logged in full);"
                " threads: %s",
                category,
                count,
                _REDISPATCH_LOG_EVERY_N,
                ", ".join(failure_thread_ids.get(category, [])),
            )


async def redispatch_reconciling_threads(
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    spawner: LazyWorkerSpawner,
    *,
    record_worker_contact: Callable[[float], None],
    trace_headers_fn: Callable[[], dict[str, str]] | None = None,
) -> None:
    """Re-dispatch RECONCILING threads after the worker is ready.

    ``reconcile_threads_on_startup`` marks threads as RECONCILING but does
    not dispatch them.  This function runs as a background task during
    lifespan startup to send them to the worker.
    """
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            threads, _ = await list_threads(
                db, status=ThreadStatus.RECONCILING, limit=100
            )
            if not threads:
                return
            # End the listing read before anything dispatches. A read
            # transaction held across a worker spawn and its HTTP call pins the
            # write-ahead log for that long and leaves every per-thread refusal
            # below upgrading a stale read into a write. Committing rather than
            # rolling back keeps the loaded rows usable: this factory does not
            # expire on commit, and a rollback would expire every one of them.
            await db.commit()
            # Start a worker only for a dispatch that survives stored-authority
            # validation; dispatch_to_worker owns that demand.
            logger.info("Re-dispatching %d reconciling threads", len(threads))
            failure_counts: dict[str, int] = {}
            failure_thread_ids: dict[str, list[str]] = {}
            for thread in threads:
                meta = _reconciling_metadata(thread)
                # Reuse the frozen effective assignment on
                # restart so the run recompiles the exact launched models, never
                # a re-resolution against possibly-drifted config.
                try:
                    frozen_map = resolve_execution_authority(
                        thread.thread_metadata
                    ).model_assignment
                except ExecutionAuthorityError as exc:
                    await _refuse_incompatible_authority(
                        db, thread, failure_counts, failure_thread_ids, exc
                    )
                    continue
                # A reconciling thread inherits the active project it was created
                # with; the sweep never re-derives one. Refusing HERE, per thread,
                # is what keeps the sweep going: constructing the dispatch without
                # a project raises inside the ingest validator, and that exception
                # aborts the whole pass, so one unrecoverable thread would strand
                # every healthy one behind it.
                workspace_root = workspace_root_from_metadata(meta)
                if workspace_root is None:
                    await _refuse_missing_project(
                        db, thread, failure_counts, failure_thread_ids
                    )
                    continue
                dispatch = await _restore_reconciling_dispatch(
                    db, thread, frozen_map, workspace_root
                )
                # The restore above read the accepted action; release that read
                # before the worker call rather than holding it across delivery.
                await db.commit()
                if dispatch is None:
                    continue
                headers = trace_headers_fn() if trace_headers_fn else {}
                try:
                    await dispatch_to_worker(
                        worker_client,
                        dispatch,
                        circuit_breaker,
                        spawner,
                        trace_headers=headers,
                    )
                    record_worker_contact(time.monotonic())
                    logger.info(
                        "Re-dispatched reconciling thread %s",
                        thread.id,
                    )
                except WorkerCircuitOpenError:
                    _log_redispatch_failure_ladder(
                        failure_counts,
                        failure_thread_ids,
                        ("circuit_open", thread.id),
                        "Circuit breaker open, skipping re-dispatch for %s",
                        thread.id,
                    )
                    continue
                except (
                    IncompatibleDispatchAuthorityError,
                    WorkerAtCapacityError,
                    WorkerDispatchRejectedError,
                    WorkerUnreachableError,
                ) as exc:
                    _log_redispatch_failure_ladder(
                        failure_counts,
                        failure_thread_ids,
                        ("redispatch_error", thread.id),
                        "Re-dispatch error for thread %s: %s",
                        thread.id,
                        exc,
                    )
            _log_redispatch_batch_summary(failure_counts, failure_thread_ids)
    except Exception as exc:
        logger.error("Reconciling re-dispatch task failed: %s", exc)


async def safe_dispatch(
    worker_client: httpx.AsyncClient,
    dispatch_request: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    *,
    trace_headers: dict[str, str] | None = None,
) -> DispatchOutcome:
    """Non-raising wrapper around :func:`dispatch_to_worker`.

    Returns a :class:`DispatchOutcome` instead of raising dispatch errors,
    making it easier for callers to handle failures without try/except
    boilerplate.
    """
    try:
        await dispatch_to_worker(
            worker_client,
            dispatch_request,
            circuit_breaker,
            worker_spawner,
            trace_headers=trace_headers,
        )
        return DispatchOutcome(success=True)
    except IncompatibleDispatchAuthorityError as exc:
        return DispatchOutcome(
            success=False,
            failure_type="incompatible_state",
            exception=exc,
            detail=str(exc),
        )
    except WorkerCircuitOpenError as exc:
        logger.warning(
            "Circuit breaker open for dispatch_id=%s thread %s: %s",
            dispatch_request.dispatch_id,
            dispatch_request.thread_id,
            exc.detail,
        )
        return DispatchOutcome(
            success=False,
            failure_type="circuit_open",
            exception=exc,
            detail=exc.detail,
        )
    except WorkerAtCapacityError as exc:
        logger.warning(
            "Worker at capacity for dispatch_id=%s thread %s",
            dispatch_request.dispatch_id,
            dispatch_request.thread_id,
        )
        return DispatchOutcome(
            success=False,
            failure_type=FailureType.AT_CAPACITY.value,
            exception=exc,
            detail=str(exc),
            retry_after_seconds=exc.retry_after_seconds,
        )
    except WorkerUnreachableError as exc:
        logger.warning(
            "Worker unreachable for dispatch_id=%s thread %s",
            dispatch_request.dispatch_id,
            dispatch_request.thread_id,
        )
        return DispatchOutcome(
            success=False,
            failure_type="unreachable",
            exception=exc,
            detail=str(exc),
        )
    except WorkerDispatchRejectedError as exc:
        logger.warning(
            "Worker rejected dispatch_id=%s thread %s (status %d)",
            dispatch_request.dispatch_id,
            dispatch_request.thread_id,
            exc.status_code,
        )
        return DispatchOutcome(
            success=False,
            failure_type=_rejected_failure_type(exc).value,
            exception=exc,
            detail=str(exc),
        )


def _rejected_failure_type(exc: WorkerDispatchRejectedError) -> FailureType:
    """Adopt the worker's own condition when it named one this layer knows.

    A worker that refuses for a reason - the thread already has a turn running,
    the dispatch authority does not match - has classified the outcome better
    than the status code can. Collapsing every refusal into ``rejected`` made a
    duplicate delivery indistinguishable from a broken request, and the recovery
    coordinator then released work that was in fact being done.
    """
    if exc.condition is None:
        return FailureType.REJECTED
    try:
        return FailureType(exc.condition)
    except ValueError:
        return FailureType.REJECTED
