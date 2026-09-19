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
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx

from ..database import (
    ThreadStatusElectionOutcome,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_session_factory,
    list_threads,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ..ipc.schemas import (
    DispatchRequest,
    DispatchResponse,
)
from ..thread.enums import ThreadStatus
from ..utils.coercion import coerce_object_mapping
from ._thread_metadata import workspace_root_from_metadata
from .accepted_input import AcceptedActionInput, restore_accepted_dispatch
from .dispatch_receipts import bind_graph_action_receipt
from .execution_authority import ExecutionAuthorityError, resolve_execution_authority

if TYPE_CHECKING:
    from collections.abc import Callable

    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "DispatchError",
    "DispatchOutcome",
    "WorkerAtCapacityError",
    "WorkerCircuitOpenError",
    "WorkerDispatchRejectedError",
    "WorkerUnreachableError",
    "dispatch_to_worker",
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

    def __init__(self, thread_id: str, dispatch_id: str) -> None:
        self.thread_id = thread_id
        self.dispatch_id = dispatch_id
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
    ) -> None:
        self.thread_id = thread_id
        self.dispatch_id = dispatch_id
        self.status_code = status_code
        self.body = body
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
    bypass_circuit_breaker: bool = False,
    trace_headers: dict[str, str] | None = None,
) -> DispatchResponse:
    """Dispatch a request to the worker process.

    Handles the common dispatch sequence:

    1. Ensure the worker is spawned via ``spawner.ensure_worker()``.
    2. Unless ``bypass_circuit_breaker`` is set, check that the circuit
       breaker allows the dispatch.
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
    if dispatch.action != "cancel":
        try:
            dispatch.require_graph_action_receipt()
        except ValueError as exc:
            raise IncompatibleDispatchAuthorityError(str(exc)) from exc
    await spawner.ensure_worker()

    # Desktop deferred reconciliation: the first authenticated execution demand to
    # complete the single-flight worker start releases the parked boot
    # reconciliation. Fire the demand-readiness signal once, only after the worker
    # is genuinely up. The signal is unset on Compose and development, whose boot
    # reconciliation is eager.
    demand_ready = spawner.demand_ready_event
    if demand_ready is not None and spawner.spawned and not demand_ready.is_set():
        demand_ready.set()

    if not bypass_circuit_breaker and not circuit_breaker.pre_dispatch():
        raise WorkerCircuitOpenError(circuit_breaker.rejection_detail)

    headers = dict(trace_headers) if trace_headers else {}

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

    if resp.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        circuit_breaker.record_failure()
        logger.warning(
            "Worker at capacity (429) for dispatch_id=%s thread %s",
            dispatch.dispatch_id,
            dispatch.thread_id,
        )
        raise WorkerAtCapacityError(
            thread_id=dispatch.thread_id,
            dispatch_id=dispatch.dispatch_id,
        )

    if not resp.is_success:
        circuit_breaker.record_failure()
        logger.warning(
            "Worker rejected dispatch_id=%s thread %s with status %d",
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

    circuit_breaker.record_success()

    return DispatchResponse(
        status="dispatched",
        thread_id=dispatch.thread_id,
    )


def _log_redispatch_failure_ladder(
    counts: dict[str, int],
    thread_ids: dict[str, list[str]],
    category: str,
    thread_id: str,
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
    counts[category] = counts.get(category, 0) + 1
    thread_ids.setdefault(category, []).append(thread_id)
    n = counts[category]
    if n == 1 or n % _REDISPATCH_LOG_EVERY_N == 0:
        logger.warning(message, *args)


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
        await spawner.ensure_worker()
        session_factory = get_session_factory()
        async with session_factory() as db:
            threads, _ = await list_threads(
                db, status=ThreadStatus.RECONCILING, limit=100
            )
            if not threads:
                return
            logger.info("Re-dispatching %d reconciling threads", len(threads))
            failure_counts: dict[str, int] = {}
            failure_thread_ids: dict[str, list[str]] = {}
            for thread in threads:
                meta: dict[str, object] = {}
                if thread.thread_metadata:
                    try:
                        raw_metadata: object = json.loads(thread.thread_metadata)
                        parsed_metadata = coerce_object_mapping(raw_metadata)
                        if parsed_metadata is not None:
                            meta = parsed_metadata
                    except json.JSONDecodeError:
                        logger.debug(
                            "Failed to parse thread metadata for %s",
                            thread.id,
                            exc_info=True,
                        )
                # Reuse the frozen effective assignment on
                # restart so the run recompiles the exact launched models, never
                # a re-resolution against possibly-drifted config.
                try:
                    frozen_map = resolve_execution_authority(
                        thread.thread_metadata
                    ).model_assignment
                except ExecutionAuthorityError as exc:
                    expectation = thread_write_expectation(thread)
                    election = await elect_thread_status(
                        db,
                        thread.id,
                        expectation=expectation,
                        status=ThreadStatus.FAILED,
                        successor=successor_thread_write_authority(
                            expectation,
                            action_type=expectation.authority.action_type,
                            action_receipt_id=(expectation.authority.action_receipt_id),
                        ),
                        failure_reason=(
                            "stored execution authority is incompatible "
                            f"({exc.reason.value})"
                        ),
                    )
                    if election.outcome is not ThreadStatusElectionOutcome.WON:
                        await db.commit()
                        logger.warning(
                            "Skipped stale reconciliation refusal for thread %s: %s",
                            thread.id,
                            election.outcome.value,
                        )
                        continue
                    await db.commit()
                    _log_redispatch_failure_ladder(
                        failure_counts,
                        failure_thread_ids,
                        "incompatible_execution_authority",
                        thread.id,
                        "Refusing incompatible execution authority (%s) for thread %s",
                        exc.reason.value,
                        thread.id,
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
                    expectation = thread_write_expectation(thread)
                    election = await elect_thread_status(
                        db,
                        thread.id,
                        expectation=expectation,
                        status=ThreadStatus.FAILED,
                        successor=successor_thread_write_authority(
                            expectation,
                            action_type=expectation.authority.action_type,
                            action_receipt_id=(expectation.authority.action_receipt_id),
                        ),
                        failure_reason=(
                            "run carries no active project: its stored metadata "
                            "names no workspace_root, so it cannot be re-sited"
                        ),
                    )
                    if election.outcome is not ThreadStatusElectionOutcome.WON:
                        await db.commit()
                        logger.warning(
                            "Skipped stale project refusal for thread %s: %s",
                            thread.id,
                            election.outcome.value,
                        )
                        continue
                    await db.commit()
                    _log_redispatch_failure_ladder(
                        failure_counts,
                        failure_thread_ids,
                        "no_active_project",
                        thread.id,
                        "Refusing to re-dispatch thread %s with no active project",
                        thread.id,
                    )
                    continue
                authority = thread_write_expectation(thread).authority
                action = await get_control_action_by_dispatch_id(
                    db,
                    thread_id=thread.id,
                    dispatch_id=authority.action_receipt_id,
                )
                if action is None or action.payload_json is None:
                    logger.warning(
                        "No accepted action for reconciling thread %s", thread.id
                    )
                    continue
                try:
                    accepted = AcceptedActionInput.model_validate_json(
                        action.payload_json
                    )
                    dispatch = restore_accepted_dispatch(
                        accepted, dispatch_id=authority.action_receipt_id
                    )
                    if dispatch.model_assignment != frozen_map or str(
                        dispatch.workspace_root
                    ) != str(workspace_root):
                        raise ValueError(
                            "accepted execution authority differs from thread metadata"
                        )
                    dispatch = await bind_graph_action_receipt(db, dispatch)
                except ValueError as exc:
                    logger.warning(
                        "Invalid accepted action for thread %s: %s", thread.id, exc
                    )
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
                        "circuit_open",
                        thread.id,
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
                        "redispatch_error",
                        thread.id,
                        "Re-dispatch error for thread %s: %s",
                        thread.id,
                        exc,
                    )
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
    except Exception as exc:
        logger.error("Reconciling re-dispatch task failed: %s", exc)


async def safe_dispatch(
    worker_client: httpx.AsyncClient,
    dispatch_request: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    *,
    bypass_circuit_breaker: bool = False,
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
            bypass_circuit_breaker=bypass_circuit_breaker,
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
            failure_type="at_capacity",
            exception=exc,
            detail=str(exc),
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
            failure_type="rejected",
            exception=exc,
            detail=str(exc),
        )
