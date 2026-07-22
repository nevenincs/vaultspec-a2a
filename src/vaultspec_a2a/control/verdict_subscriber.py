"""Engine authoring-verdict subscriber.

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
import time
from typing import TYPE_CHECKING, Any

from ..authoring import (
    VERDICT_APPROVED,
    VERDICT_REJECTED,
    AuthoringClient,
    GapSignal,
    LifecycleEvent,
    SseFrame,
    StreamError,
    approval_decision_verdict,
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
    update_thread_metadata,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest, to_dispatch_action
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

# The TeamState field carrying the proposal id of the gate a run is CURRENTLY
# parked at (committed by the submit node before the gate interrupt).
_GATE_PENDING_PROPOSAL_FIELD = "gate_pending_proposal_id"

# How often the steady-state loop re-checks still-parked runs against terminal-
# verdict proposals (the AUTO submit-time race recovery). Bounded so a legitimately
# parked HUMAN gate does not fetch a recovery snapshot every poll cycle.
_PARKED_RECONCILE_INTERVAL_SECONDS = 10.0

# The thread-metadata key holding the in-flight resume CLAIM: the gate proposal a
# resume was last dispatched for, plus its wall-clock (``time.time()``) timestamp.
# Wall clock, not monotonic: the claim is DURABLE and outlives the gateway process,
# so its staleness must remain comparable across a restart (a monotonic stamp from a
# dead process is meaningless to a fresh one and would misjudge a stale claim as
# fresh, orphaning the run). It is the
# durable "this gate's verdict is being resumed" marker written BEFORE dispatch so
# a second trigger (SSE event / reconcile sweep / gap recovery) for the SAME gate
# skips instead of double-dispatching. It is a lease, not a fire-once flag: a claim
# older than the TTL is STALE, so a still-parked run whose dispatch was lost
# (process died or dispatch failed in the claim->resume window) is legitimately
# re-driven rather than orphaned. This is an ordering symmetry applied to resume:
# durable first, liveness preserved.
_RESUME_CLAIM_FIELD = "resume_claim"

# A resume claim older than this is stale and re-drivable. Sized to cover the
# projection-lag window between a resume's checkpoint write and its durable
# side-tables landing (seconds), NOT a full re-authoring turn - a concurrent
# re-dispatch during an ACTIVE resume is already blocked by the worker's
# per-thread ingest-active lock, so the lease only guards the post-ingest window
# where the run's parked state has not yet reflected the advance.
_RESUME_CLAIM_TTL_SECONDS = 90.0


def _read_resume_claim(thread_metadata: str | None) -> tuple[str, float] | None:
    """Return ``(claimed_proposal_id, claimed_ts)`` from a thread's metadata blob."""
    if not thread_metadata:
        return None
    try:
        meta = json.loads(thread_metadata)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    claim = meta.get(_RESUME_CLAIM_FIELD)
    if not isinstance(claim, dict):
        return None
    proposal_id = claim.get("proposal_id")
    ts = claim.get("ts")
    if isinstance(proposal_id, str) and proposal_id and isinstance(ts, (int, float)):
        return proposal_id, float(ts)
    return None


def _with_resume_claim(thread_metadata: str | None, proposal_id: str, ts: float) -> str:
    """Merge a resume claim into a metadata blob, preserving every other key."""
    meta: dict[str, Any] = {}
    if thread_metadata:
        try:
            loaded = json.loads(thread_metadata)
        except (json.JSONDecodeError, TypeError):
            loaded = None
        if isinstance(loaded, dict):
            meta = loaded
    meta[_RESUME_CLAIM_FIELD] = {"proposal_id": proposal_id, "ts": ts}
    return json.dumps(meta)


def _gate_resume_verdict(status: str) -> str | None:
    """The verdict to resume a run parked at a gate whose OWN proposal reached
    ``status``.

    ``applied``/``approved`` resume the gate as approved (a changeset cannot apply
    unresolved; an AUTO gate resolves-and-applies in one synchronous step, so a
    still-parked run's proposal is observed terminal as ``applied``), ``rejected``
    resumes as rejected. A non-terminal status (``needs_review``/``draft``/...)
    carries no decision yet. This is the parked-run reconcile's LOCAL mapping - it
    admits ``applied`` where the shared `changeset_status_verdict` (gap path) does
    not, so the gap path's narrower semantics are unchanged.
    """
    if status in ("applied", "approved"):
        return VERDICT_APPROVED
    if status == "rejected":
        return VERDICT_REJECTED
    return None


def _proposal_reconcile_verdict(proposal: dict[str, Any]) -> str | None:
    """The verdict to resume a run parked at ``proposal``'s gate, if any is decided.

    Two decision signals, in precedence order:

    1. The changeset ``status`` (`_gate_resume_verdict`): recovers a missed APPROVE
       (``applied``/``approved``) or a hard ``rejected``.
    2. The resolved APPROVAL ``decision``: recovers a missed ``request_changes`` (or
       an edit-proposal reject), which returns its changeset to ``draft`` and so
       surfaces NO terminal changeset status - the reviewer decision survives only
       on the approval record. Read only when the approval is ``present`` and not
       ``stale`` (a stale decision was made against a superseded revision and must
       not resume the current gate).

    Returns ``None`` when neither signal carries a decision - the run is still
    genuinely awaiting a verdict and must stay parked, undisturbed.
    """
    verdict = _gate_resume_verdict(proposal["status"])
    if verdict is not None:
        return verdict
    approval = proposal.get("approval")
    if not isinstance(approval, dict):
        return None
    if not approval.get("present") or approval.get("stale"):
        return None
    decision = approval.get("decision")
    if isinstance(decision, str):
        return approval_decision_verdict(decision)
    return None


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
        self._last_parked_reconcile = 0.0

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
                    # Steady state: nothing new on this page. Reconcile any run
                    # left parked at a gate whose verdict was already consumed
                    # before it finished parking (the AUTO submit-time race), then
                    # poll gently.
                    await self._reconcile_parked_runs(endpoint)
                    await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.info("Authoring verdict subscriber cancelled")
            raise

    async def _reconcile_parked_runs(self, endpoint: EngineEndpoint) -> None:
        """Resume any run left parked at a gate whose verdict was already consumed.

        The AUTO race: the engine auto-approves+applies SYNCHRONOUSLY at submit and
        emits the verdict frames immediately, so the subscriber can consume them -
        and advance the forward-only cursor past them - BEFORE the run finishes the
        submit-node -> gate-node transition and becomes ``INPUT_REQUIRED``. The
        per-frame `_process_event` correlation then finds no parked thread and the
        verdict is lost. This steady-state sweep resumes each still-parked run on
        the terminal verdict of the gate it is CURRENTLY parked at.

        GATE-PRECISE by construction: a run accumulates its authoring ids across
        gates, so correlating by ANY id (as the per-event/gap path does) would let a
        LATER gate be resumed by an EARLIER gate's already-terminal verdict - e.g.
        the ADR gate spuriously resumed by the applied research verdict, completing
        the run with the ADR unreviewed. So this path keys on the run's
        ``gate_pending_proposal_id`` (the ONE proposal it is awaiting a verdict for)
        and resumes only when THAT proposal is decided. ``applied`` counts as
        approved HERE (a changeset cannot apply unresolved; an AUTO gate resolves-
        and-applies in one step, so a still-parked run's proposal reads ``applied``,
        not the transient ``approved``) - handled locally so the shared
        `changeset_status_verdict`/gap path keeps its narrower semantics.

        Reject recovery: a HUMAN ``request_changes`` (or edit-proposal
        reject) returns its changeset to ``draft``, so the changeset status carries
        NO verdict - the reviewer decision survives only on the resolved approval
        record. `_proposal_reconcile_verdict` therefore falls back to the approval
        ``decision`` (present, non-stale) to recover a missed request_changes and
        resume the parked run back into its writer's revision loop.

        Candidate set is checkpoint-truth, not status-derived: both INPUT_REQUIRED
        and RUNNING threads are considered, because a run parked at a gate can be
        left mis-statused RUNNING (a clobbered or lost gate permission event, see
        the fetch below). Idempotent and throttled; the per-thread gate_pending +
        decided-verdict + gate-precise, claim-leased resume disturbs only a run
        actually parked at a gate whose verdict is decided - a run still awaiting a
        human verdict has an undecided current proposal (no terminal status, no
        resolved approval) and a genuinely executing run has no decided gate_pending
        (or a fresh resume claim on it), so neither is ever disturbed.
        """
        now = time.monotonic()
        if now - self._last_parked_reconcile < _PARKED_RECONCILE_INTERVAL_SECONDS:
            return
        self._last_parked_reconcile = now
        async with self._session_factory() as db:
            parked, _ = await list_threads(
                db,
                status=ThreadStatus.INPUT_REQUIRED,
                limit=self._parked_thread_limit,
            )
            # recovery_required wedge: a run whose checkpoint is parked at
            # a gate interrupt can be left mis-statused RUNNING rather than
            # INPUT_REQUIRED - either because a prior gate's verdict resume set
            # RUNNING (``_resume_with_verdict``, optimistic) and that write raced
            # AFTER the next gate's permission event set INPUT_REQUIRED (a
            # cross-writer clobber), or because that gate's permission event never
            # landed. Such a run is parked-in-checkpoint but invisible to an
            # INPUT_REQUIRED-only sweep, so its decided verdict is never delivered
            # and NOTHING re-drives it. Recover by CHECKPOINT truth: also consider
            # RUNNING candidates and let the per-thread gate_pending +
            # decided-verdict + gate-precise, claim-leased ``_resume_with_verdict``
            # filter to exactly the stuck-parked runs. A genuinely executing run
            # has no decided gate_pending (or a fresh resume claim on it), so it is
            # never disturbed; a resume it does not need is rejected harmlessly by
            # the worker's ingest-active lock.
            running, _ = await list_threads(
                db,
                status=ThreadStatus.RUNNING,
                limit=self._parked_thread_limit,
            )
        candidates = list(parked)
        seen = {thread.id for thread in candidates}
        for thread in running:
            if thread.id not in seen:
                candidates.append(thread)
                seen.add(thread.id)
        if not candidates:
            return
        try:
            async with AuthoringClient(
                endpoint.base_url, endpoint.bearer_token
            ) as client:
                snapshot = await client.recovery_snapshot(last_seq=0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Parked-run reconcile snapshot fetch failed", exc_info=True)
            return
        # Map every decided proposal id (proposal + changeset) to its gate verdict,
        # so a run can be matched by its CURRENT gate proposal alone. The verdict is
        # drawn from the changeset status OR - for a missed request_changes, which
        # leaves the changeset in draft - the resolved approval decision.
        verdict_by_id: dict[str, str] = {}
        for proposal in _iter_recovery_proposals(snapshot.data):
            verdict = _proposal_reconcile_verdict(proposal)
            if verdict is None:
                continue
            for pid in proposal["ids"]:
                verdict_by_id.setdefault(pid, verdict)
        if not verdict_by_id:
            return
        for thread in candidates:
            pending = await self._thread_pending_gate_proposal(thread.id)
            if pending is None:
                continue
            verdict = verdict_by_id.get(pending)
            if verdict is not None:
                # Gate-precise by construction: keyed on the run's CURRENT gate
                # proposal, so the correlated id set is exactly that proposal.
                await self._resume_with_verdict(thread.id, verdict, None, {pending})

    async def _thread_pending_gate_proposal(self, thread_id: str) -> str | None:
        """The proposal id of the gate a run is CURRENTLY parked at.

        Read from the latest checkpoint's ``gate_pending_proposal_id`` (committed by
        the submit node before the gate parks). ``None`` when unreadable or absent -
        the run is not parked at a document gate, so the parked-run reconcile skips
        it rather than correlating a stale earlier gate's proposal.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        try:
            checkpoint_tuple = await asyncio.wait_for(
                self._checkpointer.aget_tuple(config),
                timeout=self._checkpoint_timeout,
            )
        except TimeoutError:
            logger.warning("Checkpoint read timed out for thread %s", thread_id)
            return None
        except Exception:
            logger.warning(
                "Checkpoint read failed for thread %s", thread_id, exc_info=True
            )
            return None
        if checkpoint_tuple is None:
            return None
        checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
        values: dict[str, Any] = (
            checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
        )
        pending = values.get(_GATE_PENDING_PROPOSAL_FIELD)
        return pending if isinstance(pending, str) and pending else None

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
        correlated_ids = event.correlation_ids()
        thread_id = await self._find_parked_thread(correlated_ids)
        if thread_id is None:
            logger.debug(
                "No parked thread correlates to authoring ids %s (seq=%d)",
                sorted(correlated_ids),
                event.seq,
            )
            return
        await self._resume_with_verdict(thread_id, verdict_kind, notes, correlated_ids)

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
            correlated_ids = set(proposal["ids"])
            thread_id = await self._find_parked_thread(correlated_ids)
            if thread_id is None:
                continue
            await self._resume_with_verdict(thread_id, verdict, None, correlated_ids)

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
        self,
        thread_id: str,
        verdict: str,
        notes: str | None,
        correlated_ids: set[str],
    ) -> None:
        """Dispatch ``Command(resume={"verdict", "notes"})`` to a parked run.

        The verdict answers the document gate the run is parked at, so its durable
        permission row is resolved on a successful resume - otherwise the row is
        stranded pending while the checkpoint interrupt it belonged to is gone, and
        run-status (the authoritative recovery read) asserts ``recovery_required``
        and masks the real ``awaiting_adr_decision`` phase. Only the
        rows that existed BEFORE this resume are resolved; the next gate parks with
        its own fresh row after the run advances.

        Two ordering invariants close the intermittent request_changes-recovery
        race, both keyed on the run's CURRENT gate proposal:

        - **Gate-precision.** Resume only when the run's current
          ``gate_pending_proposal_id`` is among ``correlated_ids`` - the ids the
          caller matched the verdict on. A verdict for a SUPERSEDED gate (a late r1
          request_changes arriving after the run already re-parked at r2, matched by
          the run's ACCUMULATED authoring ids) has a current gate that is not in its
          id set, so it is skipped rather than applied to the wrong gate's interrupt
          - a stale resume that corrupts the checkpoint's interrupt lineage and
          wedges the run at ``next_nodes=[]``.
        - **Durable claim before dispatch.** A resume writes a durable claim on the
          current gate proposal BEFORE dispatching, so a second trigger for the SAME
          gate sees a fresh claim and skips instead of double-dispatching. The claim
          is a lease, not a fire-once flag: a stale claim (dispatch lost in the
          claim->resume window) is re-drivable, so a lost dispatch is retried, never
          orphaned.
        """
        async with self._session_factory() as db:
            thread = await get_thread(db, thread_id)
            if thread is None:
                return
            team_preset = thread.team_preset
            thread_metadata = thread.thread_metadata
            workspace_root = _workspace_root(thread_metadata)

        # Gate-precision: the verdict must answer the gate the run is CURRENTLY
        # parked at, not a superseded earlier gate matched by accumulated ids.
        current_gate = await self._thread_pending_gate_proposal(thread_id)
        if current_gate is None or current_gate not in correlated_ids:
            logger.debug(
                "Skipping resume for thread %s: current gate proposal %s not in "
                "verdict ids %s (superseded or not parked at a gate)",
                thread_id,
                current_gate,
                sorted(correlated_ids),
            )
            return

        # Durable claim: skip a same-gate resume already in flight (fresh claim);
        # re-drive a stale one (lost dispatch). Lease keyed on the current gate.
        # Wall clock so the durable stamp stays comparable across a gateway restart.
        now = time.time()
        claim = _read_resume_claim(thread_metadata)
        if (
            claim is not None
            and claim[0] == current_gate
            and now - claim[1] < _RESUME_CLAIM_TTL_SECONDS
        ):
            logger.debug(
                "Skipping resume for thread %s: fresh resume claim on gate %s "
                "(age %.1fs < %.0fs TTL)",
                thread_id,
                current_gate,
                now - claim[1],
                _RESUME_CLAIM_TTL_SECONDS,
            )
            return
        # This whole-blob read-modify-write (merge the claim into the
        # ``thread_metadata`` read at the top of dispatch, write it all back) is
        # lost-update-safe ONLY because the verdict subscriber is the sole writer
        # of ``thread_metadata`` after thread creation. A second concurrent writer
        # elsewhere would silently clobber this claim, reopening the
        # claim->resume race the lease exists to close.
        async with self._session_factory() as db:
            await update_thread_metadata(
                db, thread_id, _with_resume_claim(thread_metadata, current_gate, now)
            )
            await db.commit()

        async with self._session_factory() as db:
            parked_gate_request_ids = [
                permission.request_id
                for permission in await get_pending_permission_requests(
                    db, thread_id=thread_id
                )
                if permission.pause_reason_type == "document_approval_request"
            ]

        resume_value: dict[str, str | None] = {"verdict": verdict, "notes": notes}
        dispatch = DispatchRequest(
            action=to_dispatch_action(ControlActionType.RESUME),
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
            # past the gate's checkpoint interrupt.
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
    """Extract ``{status, ids, approval}`` per proposal from a recovery snapshot.

    Defensive against the engine's evolving projection shape: only the
    ``changeset_id``, ``status``, and nested ``approval`` object (its
    ``proposal_id`` for correlation, plus ``decision``/``present``/``stale`` for the
    missed-request_changes recovery) are read, and anything malformed is skipped
    rather than raised on. ``approval`` is carried through verbatim (``None`` when
    absent) for `_proposal_reconcile_verdict` to read the reviewer decision the
    changeset status alone does not surface.
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
        approval_obj = approval if isinstance(approval, dict) else None
        if approval_obj is not None:
            proposal_id = approval_obj.get("proposal_id")
            if isinstance(proposal_id, str) and proposal_id:
                ids.add(proposal_id)
        if ids:
            out.append({"status": status, "ids": ids, "approval": approval_obj})
    return out


def _recovery_high_water(data: Any) -> int | None:
    """Read ``latest_outbox_seq`` from a recovery-snapshot payload, if present."""
    if isinstance(data, dict):
        value = data.get("latest_outbox_seq")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None
