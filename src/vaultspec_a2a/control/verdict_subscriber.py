"""Engine authoring-verdict subscriber (ADR R3, P03.S07).

A supervised background consumer of the dashboard engine's authoring lifecycle
stream. It resolves a live engine, reads its persisted cursor, opens
``GET /authoring/v1/events`` from that cursor, and for each reviewer verdict it
correlates the event to a parked run and resumes that run with the verdict.

Correlation flows through run state, not a side table: a parked thread's
checkpointed ``TeamState`` carries the ``authoring_proposal_ids`` /
``authoring_changeset_ids`` the run produced; an inbound event names the same
ids (as its aggregate id or in its payload data). The matched run is resumed via
the existing worker dispatch path with ``Command(resume={"verdict", "notes"})``
- the identical seam the permission-response service uses, differing only in the
resume value shape.

The engine serves a bounded replay page and closes the stream, so the loop
polls: consume a page, advance the durable cursor per event, re-open from the
new cursor. A ``gap`` frame (replay window exceeded) falls back to the recovery
snapshot to reconcile terminal verdicts, then jumps the cursor to the engine's
high-water mark. The loop is cancellation-safe: an ``asyncio.CancelledError``
propagates cleanly and closes the active stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from ..authoring import (
    AuthoringClient,
    GapSignal,
    LifecycleEvent,
    SseFrame,
    StreamError,
    changeset_status_verdict,
    verdict_from_event,
)
from ..database import (
    ThreadStatus,
    get_authoring_cursor,
    get_pending_permission_requests,
    get_thread,
    list_threads,
    mark_permission_request_applied,
    set_authoring_cursor,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest
from ..thread.enums import ControlActionType
from .dispatch import safe_dispatch

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.runnables import RunnableConfig
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..authoring import EngineEndpoint
    from ..database.checkpoints import Checkpointer
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = ["VerdictSubscriber"]

logger = logging.getLogger(__name__)

# TeamState reference fields that carry the engine ids a run produced.
_STATE_ID_FIELDS = ("authoring_proposal_ids", "authoring_changeset_ids")


class VerdictSubscriber:
    """Consume engine authoring verdicts and resume the runs they belong to."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        checkpointer: Checkpointer,
        worker_client: Any,
        circuit_breaker: WorkerCircuitBreaker,
        worker_spawner: LazyWorkerSpawner,
        endpoint_provider: Callable[[], EngineEndpoint | None],
        recursion_limit: int,
        trace_headers_fn: Callable[[], dict[str, str]] | None = None,
        poll_interval_seconds: float = 3.0,
        reconnect_base_seconds: float = 2.0,
        reconnect_max_seconds: float = 30.0,
        checkpoint_timeout_seconds: float = 10.0,
        parked_thread_limit: int = 200,
    ) -> None:
        self._session_factory = session_factory
        self._checkpointer = checkpointer
        self._worker_client = worker_client
        self._circuit_breaker = circuit_breaker
        self._worker_spawner = worker_spawner
        self._endpoint_provider = endpoint_provider
        self._recursion_limit = recursion_limit
        self._trace_headers_fn = trace_headers_fn
        self._poll_interval = poll_interval_seconds
        self._reconnect_base = reconnect_base_seconds
        self._reconnect_max = reconnect_max_seconds
        self._checkpoint_timeout = checkpoint_timeout_seconds
        self._parked_thread_limit = parked_thread_limit

    # ------------------------------------------------------------------
    # Supervised loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the poll/consume loop until cancelled.

        Resilient by construction: a missing engine or a stream failure backs off
        exponentially and retries rather than terminating the task, so the
        subscriber self-heals across engine restarts and transient outages.
        """
        backoff = self._reconnect_base
        logger.info("Authoring verdict subscriber started")
        try:
            while True:
                # ``endpoint_provider`` (``resolve_engine``) does blocking file
                # reads and a blocking ``/health`` probe; keep it off the shared
                # event loop so a slow probe never stalls the gateway.
                endpoint = await asyncio.to_thread(self._endpoint_provider)
                if endpoint is None:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self._reconnect_max)
                    continue
                try:
                    processed = await self._consume_page(endpoint)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "Verdict subscriber page failed; backing off",
                        exc_info=True,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self._reconnect_max)
                    continue
                backoff = self._reconnect_base
                if processed == 0:
                    # Steady state: nothing new on this page, poll gently.
                    await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.info("Authoring verdict subscriber cancelled")
            raise

    # ------------------------------------------------------------------
    # Page consumption
    # ------------------------------------------------------------------

    async def _consume_page(self, endpoint: EngineEndpoint) -> int:
        """Open one lifecycle page and process every frame; return frame count."""
        last_seq = await self._read_cursor()
        processed = 0
        async with AuthoringClient(endpoint.base_url, endpoint.bearer_token) as client:
            async for frame in client.stream_lifecycle(last_seq=last_seq):
                await self._process_frame(client, frame)
                processed += 1
        return processed

    async def _process_frame(self, client: AuthoringClient, frame: SseFrame) -> None:
        """Route one decoded SSE frame to its handler and advance the cursor.

        A ``StreamError`` ends the page (raised for the loop to back off); a
        ``GapSignal`` triggers recovery reconciliation; a ``LifecycleEvent`` is
        correlated-and-resumed, then its sequence is committed as the cursor.
        """
        if isinstance(frame, StreamError):
            logger.warning(
                "Engine lifecycle stream error: %s (%s)",
                frame.error,
                frame.error_kind,
            )
            # A store-side error ends the page; back off and retry.
            raise _StreamInterruptedError(frame.error_kind)
        if isinstance(frame, GapSignal):
            await self._handle_gap(client, frame)
            return
        await self._process_event(frame)
        await self._advance_cursor(frame.seq)

    async def _process_event(self, event: LifecycleEvent) -> None:
        """Resume the run a resolving event belongs to; ignore non-verdicts."""
        verdict = verdict_from_event(event)
        if verdict is None:
            return
        verdict_kind, notes = verdict
        thread_id = await self._find_parked_thread(event.correlation_ids())
        if thread_id is None:
            logger.debug(
                "No parked thread correlates to authoring ids %s (seq=%d)",
                sorted(event.correlation_ids()),
                event.seq,
            )
            return
        await self._resume_with_verdict(thread_id, verdict_kind, notes)

    # ------------------------------------------------------------------
    # Gap recovery
    # ------------------------------------------------------------------

    async def _handle_gap(self, client: AuthoringClient, gap: GapSignal) -> None:
        """Reconcile terminal verdicts from the recovery snapshot after a gap.

        The replay window was exceeded, so per-event resume is impossible for the
        skipped range. The recovery snapshot lists current proposal statuses;
        every proposal now in a terminal verdict state whose id correlates to a
        still-parked run is resumed. The cursor then jumps to the engine's
        high-water mark so live streaming continues from there.
        """
        logger.warning(
            "Authoring lifecycle gap: %s (latest_outbox_seq=%s)",
            gap.reason,
            gap.latest_outbox_seq,
        )
        try:
            snapshot = await client.recovery_snapshot(
                last_seq=gap.latest_outbox_seq or 0
            )
        except Exception:
            logger.warning("Recovery snapshot fetch failed", exc_info=True)
            return

        await self._reconcile_recovery(snapshot.data)

        high_water = gap.latest_outbox_seq
        if high_water is None:
            high_water = _recovery_high_water(snapshot.data)
        if high_water is not None:
            await self._advance_cursor(high_water)

    async def _reconcile_recovery(self, snapshot_data: Any) -> None:
        """Resume parked runs for terminal-verdict proposals in a recovery snapshot.

        Pure over the decoded snapshot payload: every proposal now in a terminal
        verdict status whose id correlates to a still-parked run is resumed with
        that verdict. Non-verdict statuses and uncorrelated proposals are skipped.
        """
        for proposal in _iter_recovery_proposals(snapshot_data):
            verdict = changeset_status_verdict(proposal["status"])
            if verdict is None:
                continue
            thread_id = await self._find_parked_thread(proposal["ids"])
            if thread_id is None:
                continue
            await self._resume_with_verdict(thread_id, verdict, None)

    # ------------------------------------------------------------------
    # Correlation
    # ------------------------------------------------------------------

    async def _find_parked_thread(self, ids: set[str]) -> str | None:
        """Return the parked thread whose recorded authoring ids intersect ``ids``.

        Only ``INPUT_REQUIRED`` threads are candidates - a run parked at a gate
        interrupt. Once resumed a run leaves that status, so a replayed verdict
        finds no match and is a safe no-op.
        """
        if not ids:
            return None
        async with self._session_factory() as db:
            threads, _ = await list_threads(
                db, status=ThreadStatus.INPUT_REQUIRED, limit=self._parked_thread_limit
            )
        for thread in threads:
            state_ids = await self._thread_authoring_ids(thread.id)
            if state_ids & ids:
                return thread.id
        return None

    async def _thread_authoring_ids(self, thread_id: str) -> set[str]:
        """Read a thread's authoring reference ids from its latest checkpoint."""
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        try:
            checkpoint_tuple = await asyncio.wait_for(
                self._checkpointer.aget_tuple(config),
                timeout=self._checkpoint_timeout,
            )
        except TimeoutError:
            logger.warning("Checkpoint read timed out for thread %s", thread_id)
            return set()
        except Exception:
            logger.warning(
                "Checkpoint read failed for thread %s", thread_id, exc_info=True
            )
            return set()
        if checkpoint_tuple is None:
            return set()
        checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
        values: dict[str, Any] = (
            checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
        )
        out: set[str] = set()
        for field in _STATE_ID_FIELDS:
            value = values.get(field)
            if isinstance(value, list):
                out.update(item for item in value if isinstance(item, str) and item)
        return out

    # ------------------------------------------------------------------
    # Resume dispatch
    # ------------------------------------------------------------------

    async def _resume_with_verdict(
        self, thread_id: str, verdict: str, notes: str | None
    ) -> None:
        """Dispatch ``Command(resume={"verdict", "notes"})`` to a parked run.

        The verdict answers the document gate the run is parked at, so its durable
        permission row is resolved on a successful resume - otherwise the row is
        stranded pending while the checkpoint interrupt it belonged to is gone, and
        run-status (the authoritative recovery read) asserts ``recovery_required``
        and masks the real ``awaiting_adr_decision`` phase (P04.S10 GAP D). Only the
        rows that existed BEFORE this resume are resolved; the next gate parks with
        its own fresh row after the run advances.
        """
        async with self._session_factory() as db:
            thread = await get_thread(db, thread_id)
            if thread is None:
                return
            team_preset = thread.team_preset
            workspace_root = _workspace_root(thread.thread_metadata)
            parked_gate_request_ids = [
                permission.request_id
                for permission in await get_pending_permission_requests(
                    db, thread_id=thread_id
                )
                if permission.pause_reason_type == "document_approval_request"
            ]

        resume_value: dict[str, str | None] = {"verdict": verdict, "notes": notes}
        dispatch = DispatchRequest(
            action=ControlActionType.RESUME,  # ty: ignore[invalid-argument-type]
            thread_id=thread_id,
            option_id=resume_value,
            team_preset=team_preset,
            workspace_root=workspace_root,
            recursion_limit=self._recursion_limit,
        )
        trace_headers = self._trace_headers_fn() if self._trace_headers_fn else None
        logger.info(
            "Resuming thread %s with verdict=%s (dispatch_id=%s)",
            thread_id,
            verdict,
            dispatch.dispatch_id,
        )
        outcome = await safe_dispatch(
            self._worker_client,
            dispatch,
            self._circuit_breaker,
            self._worker_spawner,
            trace_headers=trace_headers,
        )
        if not outcome.success:
            logger.warning(
                "Verdict resume dispatch failed for thread %s: %s",
                thread_id,
                outcome.detail,
            )
            return
        async with self._session_factory() as db:
            # Resolve the answered gate's durable permission row(s) so run-status
            # does not strand them as recovery_required drift once the run advances
            # past the gate's checkpoint interrupt (GAP D).
            for request_id in parked_gate_request_ids:
                await mark_permission_request_applied(db, request_id=request_id)
            await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
            await db.commit()

    # ------------------------------------------------------------------
    # Cursor persistence
    # ------------------------------------------------------------------

    async def _read_cursor(self) -> int:
        async with self._session_factory() as db:
            return await get_authoring_cursor(db)

    async def _advance_cursor(self, last_seq: int) -> None:
        async with self._session_factory() as db:
            await set_authoring_cursor(db, last_seq=last_seq)
            await db.commit()


class _StreamInterruptedError(Exception):
    """Internal signal that a store-side ``error`` frame ended the page."""


def _workspace_root(thread_metadata: str | None) -> str | None:
    """Extract ``workspace_root`` from a thread's JSON metadata blob."""
    if not thread_metadata:
        return None
    try:
        meta = json.loads(thread_metadata)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(meta, dict):
        root = meta.get("workspace_root")
        return root if isinstance(root, str) else None
    return None


def _iter_recovery_proposals(data: Any) -> list[dict[str, Any]]:
    """Extract ``{status, ids}`` per proposal from a recovery-snapshot payload.

    Defensive against the engine's evolving projection shape: only the
    ``changeset_id``, ``status``, and nested ``approval.proposal_id`` fields are
    read, and anything malformed is skipped rather than raised on.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return out
    snapshot = data.get("snapshot")
    if not isinstance(snapshot, dict):
        return out
    proposals = snapshot.get("proposals")
    items: Any = None
    if isinstance(proposals, dict):
        items = proposals.get("items")
    elif isinstance(proposals, list):
        items = proposals
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if not isinstance(status, str):
            continue
        ids: set[str] = set()
        changeset_id = item.get("changeset_id")
        if isinstance(changeset_id, str) and changeset_id:
            ids.add(changeset_id)
        approval = item.get("approval")
        if isinstance(approval, dict):
            proposal_id = approval.get("proposal_id")
            if isinstance(proposal_id, str) and proposal_id:
                ids.add(proposal_id)
        if ids:
            out.append({"status": status, "ids": ids})
    return out


def _recovery_high_water(data: Any) -> int | None:
    """Read ``latest_outbox_seq`` from a recovery-snapshot payload, if present."""
    if isinstance(data, dict):
        value = data.get("latest_outbox_seq")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None
