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
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from ..authoring import (
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
    begin_write_transaction,
    get_authoring_cursor,
    get_pending_permission_requests,
    get_thread,
    list_threads,
    mark_control_action_applied,
    mark_permission_request_applied,
    set_authoring_cursor,
    thread_write_expectation,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.dispatch_policy import evaluate_dispatch_failure
from ..thread.enums import (
    VERDICT_APPROVED,
    VERDICT_REJECTED,
    ControlActionType,
    ThreadStatus,
)
from ..utils.coercion import coerce_object_list, coerce_object_mapping
from ._thread_metadata import dispatchable_workspace_root
from .accepted_input import freeze_accepted_input
from .action_lease import (
    ControlActionClaimRequest,
    finalize_control_action_acceptance,
    prepare_control_action_claim,
    record_dispatch_failure,
)
from .dispatch import safe_dispatch
from .dispatch_receipts import bind_graph_action_receipt
from .execution_authority import ExecutionAuthorityError, resolve_execution_authority
from .graph_definition import read_accepted_graph_definition

if TYPE_CHECKING:
    from collections.abc import Mapping

    from langchain_core.runnables import RunnableConfig
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..authoring import EngineEndpoint
    from ..database import ControlActionModel, ThreadWriteExpectation
    from ..thread.executable_graph import FrozenGraphDefinition
    from ._verdict_subscriber_config import VerdictSubscriberConfig

__all__ = [
    "VerdictSubscriber",
    "settle_verdict_dispatch_receipt",
]

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


class _RecoveryProposal(TypedDict):
    """The recovery fields needed to reconcile one engine proposal."""

    status: str
    ids: set[str]
    approval: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class _VerdictSetup:
    dispatch: DispatchRequest
    write_expectation: ThreadWriteExpectation
    current_gate: str
    resume_value: dict[str, object]
    graph_definition: FrozenGraphDefinition


def _verdict_resume_idempotency_key(proposal_id: str) -> str:
    """Return the request-level journal key for one document-gate verdict."""
    return f"authoring-verdict:{proposal_id}"


def _verdict_resume_payload(verdict: str, notes: str | None) -> dict[str, object]:
    """Return the typed durable payload dispatched for a verdict resume."""
    return {"verdict": verdict, "notes": notes}


async def settle_verdict_dispatch_receipt(
    db: AsyncSession,
    action: ControlActionModel,
) -> bool:
    """Apply an exact worker receipt for one authoring-verdict resume.

    Stable dispatch identity selects the action before this helper is called. The
    journal key then distinguishes verdict resumes from clarification and permission
    resumes that share the same wire action but have different application owners.
    The caller owns the transaction commit.
    """
    if (
        action.action_type != ControlActionType.RESUME.value
        or not action.idempotency_key.startswith("authoring-verdict:")
        or action.applied_at is not None
    ):
        return False
    await mark_control_action_applied(db, action.id)
    pending = await get_pending_permission_requests(db, thread_id=action.thread_id)
    for permission in pending:
        if permission.pause_reason_type == "document_approval_request":
            await mark_permission_request_applied(db, request_id=permission.request_id)
    await update_thread_status(db, action.thread_id, ThreadStatus.RUNNING)
    return True


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


def _proposal_reconcile_verdict(proposal: _RecoveryProposal) -> str | None:
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
    if approval is None:
        return None
    if not approval.get("present") or approval.get("stale"):
        return None
    decision = approval.get("decision")
    if isinstance(decision, str):
        return approval_decision_verdict(decision)
    return None


def _decided_verdicts(data: object) -> dict[str, str]:
    verdict_by_id: dict[str, str] = {}
    for proposal in _iter_recovery_proposals(data):
        verdict = _proposal_reconcile_verdict(proposal)
        if verdict is None:
            continue
        for proposal_id in proposal["ids"]:
            verdict_by_id.setdefault(proposal_id, verdict)
    return verdict_by_id


def _checkpoint_authoring_ids(checkpoint: object) -> set[str]:
    checkpoint_mapping = coerce_object_mapping(checkpoint)
    values = (
        coerce_object_mapping(checkpoint_mapping.get("channel_values"))
        if checkpoint_mapping is not None
        else None
    )
    if values is None:
        return set()
    out: set[str] = set()
    for field in _STATE_ID_FIELDS:
        items = coerce_object_list(values.get(field))
        if items is not None:
            out.update(item for item in items if isinstance(item, str) and item)
    return out


class VerdictSubscriber:
    """Consume engine authoring verdicts and resume the runs they belong to."""

    def __init__(self, config: VerdictSubscriberConfig) -> None:
        self._dependencies = config.dependencies
        self._execution = config.execution
        self._timing = config.timing
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
        backoff = self._timing.reconnect_base_seconds
        logger.info("Authoring verdict subscriber started")
        try:
            while True:
                # ``endpoint_provider`` (``resolve_engine``) does blocking file
                # reads and a blocking ``/health`` probe; keep it off the shared
                # event loop so a slow probe never stalls the gateway.
                endpoint = await asyncio.to_thread(self._dependencies.endpoint_provider)
                if endpoint is None:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self._timing.reconnect_max_seconds)
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
                    backoff = min(backoff * 2, self._timing.reconnect_max_seconds)
                    continue
                backoff = self._timing.reconnect_base_seconds
                if processed == 0:
                    # Steady state: nothing new on this page. Reconcile any run
                    # left parked at a gate whose verdict was already consumed
                    # before it finished parking (the AUTO submit-time race), then
                    # poll gently.
                    await self._reconcile_parked_runs(endpoint)
                    await asyncio.sleep(self._timing.poll_interval_seconds)
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
        candidates = await self._parked_candidate_ids()
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
        verdict_by_id = _decided_verdicts(snapshot.data)
        if not verdict_by_id:
            return
        for thread_id in candidates:
            pending = await self._thread_pending_gate_proposal(thread_id)
            if pending is None:
                continue
            verdict = verdict_by_id.get(pending)
            if verdict is not None:
                # Gate-precise by construction: keyed on the run's CURRENT gate
                # proposal, so the correlated id set is exactly that proposal.
                await self._resume_with_verdict(thread_id, verdict, None, {pending})

    async def _parked_candidate_ids(self) -> list[str]:
        async with self._dependencies.session_factory() as db:
            parked, _ = await list_threads(
                db,
                status=ThreadStatus.INPUT_REQUIRED,
                limit=self._timing.parked_thread_limit,
            )
            # A checkpoint parked at a gate can be mis-statused RUNNING when a
            # prior receipt races the gate event. The gate-precise claim below
            # filters these candidates by checkpoint truth.
            running, _ = await list_threads(
                db,
                status=ThreadStatus.RUNNING,
                limit=self._timing.parked_thread_limit,
            )
        candidates = [thread.id for thread in parked]
        seen = set(candidates)
        for thread in running:
            if thread.id not in seen:
                candidates.append(thread.id)
                seen.add(thread.id)
        return candidates

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
                self._dependencies.checkpointer.aget_tuple(config),
                timeout=self._timing.checkpoint_timeout_seconds,
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
        checkpoint: object = getattr(checkpoint_tuple, "checkpoint", None)
        checkpoint_mapping = coerce_object_mapping(checkpoint)
        values = (
            coerce_object_mapping(checkpoint_mapping.get("channel_values"))
            if checkpoint_mapping is not None
            else None
        )
        if values is None:
            return None
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

    async def _reconcile_recovery(self, snapshot_data: object) -> None:
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
        async with self._dependencies.session_factory() as db:
            threads, _ = await list_threads(
                db,
                status=ThreadStatus.INPUT_REQUIRED,
                limit=self._timing.parked_thread_limit,
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
                self._dependencies.checkpointer.aget_tuple(config),
                timeout=self._timing.checkpoint_timeout_seconds,
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
        return _checkpoint_authoring_ids(getattr(checkpoint_tuple, "checkpoint", None))

    # ------------------------------------------------------------------
    # Resume dispatch
    # ------------------------------------------------------------------

    async def _prepare_verdict_resume(
        self,
        thread_id: str,
        verdict: str,
        notes: str | None,
        correlated_ids: set[str],
    ) -> _VerdictSetup | None:
        async with self._dependencies.session_factory() as db:
            thread = await get_thread(db, thread_id)
            if thread is None:
                return
            team_preset = thread.team_preset
            thread_metadata = thread.thread_metadata
            write_expectation = thread_write_expectation(thread)
            workspace_root = dispatchable_workspace_root(thread_metadata)
            if workspace_root is None:
                logger.warning(
                    "Refusing verdict resume: accepted project unavailable",
                    extra={"thread_id": thread_id, "failure_type": "no_active_project"},
                )
                return
            try:
                graph_definition = await read_accepted_graph_definition(db, thread_id)
                team_preset = graph_definition.team_id
                execution_authority = resolve_execution_authority(thread_metadata)
            except (ExecutionAuthorityError, ValueError) as exc:
                logger.warning(
                    "Refusing verdict resume for thread %s: %s", thread_id, exc
                )
                return

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

        resume_value = _verdict_resume_payload(verdict, notes)
        dispatch = DispatchRequest(
            action=to_dispatch_action(ControlActionType.RESUME),
            thread_id=thread_id,
            option_id=resume_value,
            team_preset=team_preset,
            graph_definition=graph_definition,
            workspace_root=workspace_root,
            recursion_limit=self._execution.recursion_limit,
            model_assignment=execution_authority.model_assignment,
        )
        return _VerdictSetup(
            dispatch, write_expectation, current_gate, resume_value, graph_definition
        )

    async def _resume_with_verdict(
        self,
        thread_id: str,
        verdict: str,
        notes: str | None,
        correlated_ids: set[str],
    ) -> None:
        """Dispatch ``Command(resume={"verdict", "notes"})`` to a parked run.

        The worker HTTP response acknowledges scheduling only. The exact internal
        ``dispatch_applied`` receipt owns journal, permission-row, and RUNNING
        settlement after graph execution actually begins.

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
        - **Durable lease before dispatch.** The shared control-action journal
          reserves the current gate's typed verdict and atomically elects one lease
          owner before dispatch. Identical fresh replays skip, competing verdict
          payloads conflict without replacing the winner, and an expired lease is
          re-drivable so a lost dispatch never permanently orphans the run.
        """
        setup = await self._prepare_verdict_resume(
            thread_id, verdict, notes, correlated_ids
        )
        if setup is None:
            return
        dispatch = setup.dispatch
        async with self._dependencies.session_factory() as db:
            await begin_write_transaction(db)
            claim = await prepare_control_action_claim(
                db,
                request=ControlActionClaimRequest(
                    write_expectation=setup.write_expectation,
                    thread_id=thread_id,
                    action_type=ControlActionType.RESUME,
                    idempotency_key=_verdict_resume_idempotency_key(setup.current_gate),
                    request_id=setup.current_gate,
                    payload=freeze_accepted_input(dispatch, intent=setup.resume_value),
                    dispatch_id=dispatch.dispatch_id,
                    recovery_timeout_seconds=setup.graph_definition.run_timeout_seconds,
                ),
            )
            if not claim.authority_matches:
                logger.warning(
                    "Refused stale verdict authority for thread %s", thread_id
                )
                return
            if not claim.payload_matches:
                logger.warning(
                    "Skipping competing verdict resume for thread %s gate %s",
                    thread_id,
                    setup.current_gate,
                )
                return
            if not claim.acquired:
                logger.debug(
                    "Skipping verdict resume replay for thread %s gate %s (applied=%s)",
                    thread_id,
                    setup.current_gate,
                    claim.applied,
                )
                return
            await finalize_control_action_acceptance(db, claim)
        if claim.claim_token is None:
            raise RuntimeError("acquired verdict lease has no claim token")

        dispatch = dispatch.model_copy(update={"dispatch_id": claim.dispatch_id})
        trace_headers_fn = self._execution.trace_headers_fn
        trace_headers = trace_headers_fn() if trace_headers_fn else None
        logger.info(
            "Resuming thread %s with verdict=%s (dispatch_id=%s)",
            thread_id,
            verdict,
            dispatch.dispatch_id,
        )
        async with self._dependencies.session_factory() as db:
            dispatch = await bind_graph_action_receipt(db, dispatch)
        outcome = await safe_dispatch(
            self._dependencies.worker_client,
            dispatch,
            self._dependencies.circuit_breaker,
            self._dependencies.worker_spawner,
            trace_headers=trace_headers,
        )
        if not outcome.success:
            _policy, failure_type = evaluate_dispatch_failure(outcome.failure_type)
            async with self._dependencies.session_factory() as db:
                if failure_type is None:
                    raise RuntimeError("failed dispatch carries no failure type")
                await begin_write_transaction(db)
                await record_dispatch_failure(
                    db, claim, failure_type, detail=outcome.detail
                )
                await db.commit()
            logger.warning(
                "Verdict resume dispatch failed for thread %s: %s",
                thread_id,
                outcome.detail,
            )
            return

        # Receipt-driven settlement occurs in the worker-event handler. Keeping the
        # lease fresh here prevents an HTTP acknowledgement from masquerading as
        # graph application while preserving stable-ID replay suppression.

    # ------------------------------------------------------------------
    # Cursor persistence
    # ------------------------------------------------------------------

    async def _read_cursor(self) -> int:
        async with self._dependencies.session_factory() as db:
            return await get_authoring_cursor(db)

    async def _advance_cursor(self, last_seq: int) -> None:
        async with self._dependencies.session_factory() as db:
            await set_authoring_cursor(db, last_seq=last_seq)
            await db.commit()


class _StreamInterruptedError(Exception):
    """Internal signal that a store-side ``error`` frame ended the page."""


def _iter_recovery_proposals(data: object) -> list[_RecoveryProposal]:
    """Extract ``{status, ids, approval}`` per proposal from a recovery snapshot.

    Defensive against the engine's evolving projection shape: only the
    ``changeset_id``, ``status``, and nested ``approval`` object (its
    ``proposal_id`` for correlation, plus ``decision``/``present``/``stale`` for the
    missed-request_changes recovery) are read, and anything malformed is skipped
    rather than raised on. ``approval`` is carried through verbatim (``None`` when
    absent) for `_proposal_reconcile_verdict` to read the reviewer decision the
    changeset status alone does not surface.
    """
    out: list[_RecoveryProposal] = []
    payload = coerce_object_mapping(data)
    if payload is None:
        return out
    snapshot = coerce_object_mapping(payload.get("snapshot"))
    if snapshot is None:
        return out
    proposals = snapshot.get("proposals")
    proposal_mapping = coerce_object_mapping(proposals)
    items = (
        coerce_object_list(proposal_mapping.get("items"))
        if proposal_mapping is not None
        else coerce_object_list(proposals)
    )
    if items is None:
        return out
    for item in items:
        proposal = _recovery_proposal(item)
        if proposal is not None:
            out.append(proposal)
    return out


def _recovery_proposal(item: object) -> _RecoveryProposal | None:
    item_mapping = coerce_object_mapping(item)
    if item_mapping is None:
        return None
    status = item_mapping.get("status")
    if not isinstance(status, str):
        return None
    ids: set[str] = set()
    changeset_id = item_mapping.get("changeset_id")
    if isinstance(changeset_id, str) and changeset_id:
        ids.add(changeset_id)
    approval_obj = coerce_object_mapping(item_mapping.get("approval"))
    if approval_obj is not None:
        proposal_id = approval_obj.get("proposal_id")
        if isinstance(proposal_id, str) and proposal_id:
            ids.add(proposal_id)
    if not ids:
        return None
    return {"status": status, "ids": ids, "approval": approval_obj}


def _recovery_high_water(data: object) -> int | None:
    """Read ``latest_outbox_seq`` from a recovery-snapshot payload, if present."""
    payload = coerce_object_mapping(data)
    if payload is not None:
        value = payload.get("latest_outbox_seq")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None
