"""Build and deliver every leased dispatch through one sequence.

A follow-on dispatch re-enters a run that was already accepted: a follow-up
turn, a permission or clarification answer, a reviewer verdict. Each is rebuilt
from the run's own accepted authority - its active project, its initial graph
definition and its frozen execution authority - and never from presets or
service defaults read at some later moment.

The recursion budget is decided here too, once, at acceptance. It is frozen
into the accepted input with every other effective field, so the worker and
every later recovery run under the number admission chose rather than each
deriving one of its own.

Delivery is one sequence for every leased verb: commit the claimed acceptance,
bind its graph receipt from committed evidence, deliver it, and settle a failed
delivery on the journal. A verb keeps only what is its own: the compensations a
failure calls for and how it reports the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack

from ..database import begin_write_transaction
from ..domain_config import domain_config
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ._thread_metadata import dispatchable_workspace_root
from .action_lease import finalize_control_action_acceptance, record_dispatch_failure
from .dispatch import safe_dispatch
from .dispatch_receipts import bind_graph_action_receipt
from .execution_authority import ExecutionAuthorityError, resolve_execution_authority
from .graph_definition import read_initial_accepted_input

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread.enums import ControlActionType
    from ..thread.executable_graph import FrozenGraphDefinition
    from .action_lease import ControlActionClaim, DispatchFailureDisposition
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "DispatchFailure",
    "DispatchRefusal",
    "DispatchTransport",
    "SettledDispatchFailure",
    "accepted_recursion_budget",
    "build_followon_dispatch",
    "deliver_leased",
    "dispatch_leased",
]

_NO_ACTIVE_PROJECT = (
    "run carries no active project: its stored metadata names no usable "
    "workspace_root, so this action cannot be sited"
)


@dataclass(frozen=True, slots=True)
class DispatchTransport:
    """The worker connection one gateway-to-worker delivery travels over."""

    worker_client: httpx.AsyncClient
    circuit_breaker: WorkerCircuitBreaker
    worker_spawner: LazyWorkerSpawner
    trace_headers: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class DispatchRefusal:
    """A run or stored action that must not be dispatched, and the typed reason.

    Returning this instead of a bare ``None`` keeps the reason typed at the
    point it is known, which is what lets an absent active project be reported
    as itself rather than folded into a generic rejection at the provider seam.
    """

    failure_type: FailureType
    reason: str


@dataclass(frozen=True, slots=True)
class DispatchFailure:
    """A leased delivery the worker did not take, classified once."""

    failure_type: FailureType
    should_mark_failed: bool
    detail: str
    retry_after_seconds: float | None
    """How long the worker itself asked the caller to wait, when it said so."""


@dataclass(frozen=True, slots=True)
class SettledDispatchFailure(DispatchFailure):
    """A failed delivery whose lease the journal has already settled."""

    disposition: DispatchFailureDisposition


class _FollowonFields(TypedDict, total=False):
    option_id: str | dict[str, object]
    agent_id: str
    content: str


def accepted_recursion_budget(definition: FrozenGraphDefinition) -> int:
    """The recursion budget one accepted dispatch carries.

    The operator ceiling bounds every graph invocation, and the budget the
    accepted preset declares can only lower it.
    """
    return min(domain_config.graph_recursion_limit, definition.recursion_limit)


async def build_followon_dispatch(
    db: AsyncSession,
    *,
    thread_id: str,
    thread_metadata: str | None,
    action: ControlActionType,
    **fields: Unpack[_FollowonFields],
) -> DispatchRequest | DispatchRefusal:
    """Rebuild one graph re-entry from the run's own accepted authority.

    *thread_metadata* is the run row's stored column, passed as a value rather
    than read off the row: an acceptance that loses its claim rolls back and
    expires every loaded row, so a caller snapshots it first.
    """
    workspace_root = dispatchable_workspace_root(thread_metadata)
    if workspace_root is None:
        return DispatchRefusal(FailureType.NO_ACTIVE_PROJECT, _NO_ACTIVE_PROJECT)
    try:
        initial_input = await read_initial_accepted_input(db, thread_id)
        graph_definition = initial_input.graph_definition
        if graph_definition is None:
            raise ValueError("initial graph authority carries no graph definition")
        autonomous = initial_input.dispatch["autonomous"]
        if not isinstance(autonomous, bool):
            raise ValueError("initial graph authority carries invalid autonomy")
        execution_authority = resolve_execution_authority(thread_metadata)
    except (ExecutionAuthorityError, ValueError) as exc:
        return DispatchRefusal(FailureType.INCOMPATIBLE_STATE, str(exc))
    return DispatchRequest(
        action=to_dispatch_action(action),
        thread_id=thread_id,
        team_preset=graph_definition.team_id,
        graph_definition=graph_definition,
        autonomous=autonomous,
        workspace_root=workspace_root,
        recursion_limit=accepted_recursion_budget(graph_definition),
        model_assignment=execution_authority.model_assignment,
        **fields,
    )


async def deliver_leased(
    db: AsyncSession,
    claim: ControlActionClaim,
    dispatch: DispatchRequest,
    transport: DispatchTransport,
) -> DispatchFailure | None:
    """Commit a claimed acceptance, then deliver it under its stable identity.

    The acceptance and every projection the caller wrote beside it commit
    before anything reaches the network, so a worker that never answers leaves
    an accepted intention behind rather than nothing. ``None`` means the worker
    took the dispatch, which acknowledges scheduling only: application settles
    from the worker's own receipt. A failure is classified but not settled.
    """
    await finalize_control_action_acceptance(db, claim)
    bound = await bind_graph_action_receipt(
        db, dispatch.model_copy(update={"dispatch_id": claim.dispatch_id})
    )
    outcome = await safe_dispatch(
        transport.worker_client,
        bound,
        transport.circuit_breaker,
        transport.worker_spawner,
        trace_headers=transport.trace_headers,
    )
    if outcome.success:
        return None
    should_mark_failed, failure_type = evaluate_dispatch_failure(outcome.failure_type)
    if failure_type is None:
        raise RuntimeError("failed dispatch carries no failure type")
    return DispatchFailure(
        failure_type=failure_type,
        should_mark_failed=should_mark_failed,
        detail=outcome.detail or "Worker dispatch failed",
        retry_after_seconds=outcome.retry_after_seconds,
    )


async def dispatch_leased(
    db: AsyncSession,
    claim: ControlActionClaim,
    dispatch: DispatchRequest,
    transport: DispatchTransport,
) -> SettledDispatchFailure | None:
    """Deliver a claimed acceptance and settle a failed delivery on the journal.

    The settlement is written inside a write transaction left open for the
    caller, so the compensations its verb owes commit with it.
    """
    failure = await deliver_leased(db, claim, dispatch, transport)
    if failure is None:
        return None
    await begin_write_transaction(db)
    disposition = await record_dispatch_failure(
        db, claim, failure.failure_type, detail=failure.detail
    )
    return SettledDispatchFailure(
        failure_type=failure.failure_type,
        should_mark_failed=failure.should_mark_failed,
        detail=failure.detail,
        retry_after_seconds=failure.retry_after_seconds,
        disposition=disposition,
    )
