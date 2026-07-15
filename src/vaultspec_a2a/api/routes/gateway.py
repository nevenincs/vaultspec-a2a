"""The versioned five-verb gateway surface (ADR R6).

Mounts ``run-start``, ``run-status``, ``run-cancel``, ``presets-list``, and
``service-state`` under ``/v1`` as the engine-facing edge. Each verb reshapes an
existing service rather than reinventing it, so there is a single code path: the
richer internal ``/api`` surface and these verbs call the same services beneath.
"""

import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.cancel_service import cancel_thread
from ...control.config import settings
from ...control.health import assemble_health_status
from ...control.run_start_policy import evaluate_run_start_eligibility
from ...control.thread_service import (
    ThreadCreationRequest,
    create_and_dispatch_thread,
    generate_thread_id,
    process_metadata,
)
from ...control.thread_state_service import build_thread_state, read_run_authoring_ids
from ...database import get_thread
from ...database.checkpoints import Checkpointer
from ...database.session import get_db
from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus
from ...thread.errors import NicknameConflictError
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import (
    get_aggregator,
    get_checkpointer,
    get_circuit_breaker,
    get_services,
    get_worker_client,
    get_worker_spawner,
)
from ..schemas.gateway import (
    PresetsListResponse,
    PresetSummary,
    RoleState,
    RunCancelResponse,
    RunStartRequest,
    RunStartResponse,
    RunStatusResponse,
    ServiceStateResponse,
    TopologyPosition,
)

router = APIRouter(prefix="/v1")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# run-start
# ---------------------------------------------------------------------------


@router.post("/runs", response_model=RunStartResponse, status_code=201)
async def run_start_endpoint(
    request: Request,
    body: RunStartRequest,
    services: tuple[
        AsyncSession, EventAggregator, Checkpointer, httpx.AsyncClient
    ] = Depends(get_services),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> RunStartResponse:
    """Start a run: reshaped thread-create + first message, accepting tokens.

    Unlike the internal ``/api`` surface, the v1 verb refuses before dispatch
    rather than creating a non-running draft: an unloadable preset, a
    document-authoring preset with no target feature, or an actor-token bundle
    that does not cover the preset's roles all return a 4xx. A client-supplied
    ``run_id`` makes the verb dispatch-exactly-once under retry.
    """
    db, _aggregator, _checkpointer, worker_client = services

    # Client idempotency: a retry with the same stable run id returns the
    # existing run rather than starting a second one (dispatch-exactly-once).
    if body.run_id is not None:
        existing = await get_thread(db, body.run_id)
        if existing is not None:
            return RunStartResponse(
                run_id=existing.id,
                status=existing.status,
                nickname=existing.nickname,
                eligible=True,
            )
    run_id = body.run_id or generate_thread_id()

    # Thread the target feature onto the metadata so it reaches dispatch and the
    # vault index; the top-level field is authoritative when both are present.
    metadata = body.metadata
    if body.feature_tag and metadata is not None:
        metadata = metadata.model_copy(update={"feature_tag": body.feature_tag})

    try:
        ws_root, nickname, metadata_json = process_metadata(
            metadata, run_id, body.team_preset
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    team_config = _load_preset_or_refuse(body.team_preset, ws_root)
    effective_feature = body.feature_tag or (
        metadata.feature_tag if metadata is not None else None
    )
    eligibility = evaluate_run_start_eligibility(
        team_config,
        feature_tag=effective_feature or None,
        actor_tokens=body.actor_tokens,
    )
    if not eligibility.eligible:
        raise HTTPException(status_code=422, detail=eligibility.reason)

    try:
        result = await create_and_dispatch_thread(
            db,
            ThreadCreationRequest(
                thread_id=run_id,
                title=body.title,
                initial_message=body.message,
                team_preset=body.team_preset,
                autonomous=body.autonomous,
                nickname=nickname,
                metadata=metadata,
                metadata_json=metadata_json,
                workspace_root=ws_root,
                actor_tokens=body.actor_tokens,
            ),
            circuit_breaker=circuit_breaker,
            worker_spawner=worker_spawner,
            worker_client=worker_client,
            recursion_limit=domain_config.graph_recursion_limit,
            trace_headers=trace_headers(),
        )
    except NicknameConflictError as exc:
        raise HTTPException(
            status_code=409, detail=f"Run nickname already exists: {exc.nickname!r}"
        ) from exc

    if result.dispatched:
        mark_worker_connected(request)

    _raise_for_dispatch_failure(result.failure_type, result.error_detail)

    return RunStartResponse(
        run_id=result.thread_id, status=result.status, nickname=result.nickname
    )


def _load_preset_or_refuse(team_preset: str, ws_root: Path | None) -> Any:
    """Load the preset with the run's workspace context or refuse with a 422.

    The v1 verb never silently drafts a run for a missing or unparseable preset:
    a load or validation failure is a client error, returned as a 422 with a safe
    reason rather than a non-running draft.
    """
    from pydantic import ValidationError

    from ...team.team_config import load_team_config
    from ...thread.errors import ConfigError, TeamConfigNotFoundError

    try:
        return load_team_config(team_preset, workspace_root=ws_root)
    except TeamConfigNotFoundError as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown team preset: {team_preset!r}"
        ) from exc
    except (ConfigError, ValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Team preset {team_preset!r} failed to load: {exc}",
        ) from exc


def _raise_for_dispatch_failure(
    failure_type: FailureType | None, detail: str | None
) -> None:
    """Map a dispatch failure to the same HTTP status the internal route uses."""
    if failure_type is None:
        return
    if failure_type == FailureType.CIRCUIT_OPEN:
        raise HTTPException(status_code=503, detail=detail or "Circuit breaker open")
    if failure_type == FailureType.AT_CAPACITY:
        raise HTTPException(status_code=503, detail="Worker at capacity — try again")
    if failure_type == FailureType.UNREACHABLE:
        raise HTTPException(status_code=502, detail="Worker unreachable")
    if failure_type == FailureType.REJECTED:
        raise HTTPException(
            status_code=502, detail=detail or "Worker dispatch rejected"
        )


# ---------------------------------------------------------------------------
# run-status
# ---------------------------------------------------------------------------


def _active_agent(next_nodes: list[str]) -> str | None:
    """Best-effort active agent from the checkpoint's next nodes.

    Strips the ADR-020 ``mount_`` prefix so the position names the worker, not
    its mount stage; the supervisor and gate nodes pass through unchanged.
    """
    for node in next_nodes:
        if node and node != "__end__":
            return node.removeprefix("mount_")
    return None


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def run_status_endpoint(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> RunStatusResponse:
    """Return the authoritative recovery snapshot for a run (ADR R6)."""
    snapshot = await build_thread_state(
        db, thread_id=run_id, aggregator=aggregator, checkpointer=checkpointer
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Run not found")

    thread = await get_thread(db, run_id)
    team_preset = thread.team_preset if thread is not None else None
    proposal_ids, changeset_ids = await read_run_authoring_ids(checkpointer, run_id)

    return RunStatusResponse(
        run_id=snapshot.thread_id,
        status=ThreadStatus(snapshot.status),
        topology=TopologyPosition(
            team_preset=team_preset,
            active_agent=_active_agent(snapshot.next_nodes),
            next_nodes=snapshot.next_nodes,
            pause_cause=snapshot.pause_cause,
        ),
        roles=[
            RoleState(
                agent_id=agent.agent_id,
                role=agent.role,
                state=agent.state,
                display_name=agent.display_name,
            )
            for agent in snapshot.agents
        ],
        proposal_ids=proposal_ids,
        changeset_ids=changeset_ids,
        approval_status=snapshot.approval_status,
        approval_request_id=snapshot.approval_request_id,
        checkpoint_id=snapshot.checkpoint_id,
        last_sequence=snapshot.last_sequence,
        repair_status=snapshot.repair_status,
        execution_readiness=snapshot.execution_readiness,
        degraded_reasons=snapshot.degraded_reasons,
    )


# ---------------------------------------------------------------------------
# run-cancel
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/cancel", response_model=RunCancelResponse)
async def run_cancel_endpoint(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunCancelResponse:
    """Cancel a run idempotently."""
    result = await cancel_thread(
        db=db,
        thread_id=run_id,
        idempotency_key=idempotency_key,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )

    if result.failure_type == FailureType.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Run not found")
    if result.failure_type is not None:
        raise HTTPException(
            status_code=502, detail=result.error_detail or "Cancel dispatch failed"
        )

    if result.cancelled:
        mark_worker_connected(request)

    return RunCancelResponse(
        run_id=result.thread_id,
        status=result.thread_status,
        cancelled=result.cancelled,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        idempotency_key=result.idempotency_key,
    )


# ---------------------------------------------------------------------------
# presets-list
# ---------------------------------------------------------------------------


@router.get("/presets", response_model=PresetsListResponse)
async def presets_list_endpoint(
    workspace_root: str | None = Query(default=None, max_length=4096),
) -> PresetsListResponse:
    """List team presets truthfully, marking each loadable or unloadable.

    Resolution uses the requested workspace context so workspace-local presets
    are listed alongside the bundled set. A single preset that fails to load or
    validate is reported with ``loadable=False`` and a reason rather than
    omitted or allowed to crash the whole listing.
    """
    from ...team.team_config import discover_team_preset_ids

    ws_root = Path(workspace_root) if workspace_root else None
    presets = [
        _summarize_preset(preset_id, ws_root)
        for preset_id in sorted(discover_team_preset_ids(ws_root))
    ]
    return PresetsListResponse(presets=presets)


def _summarize_preset(preset_id: str, ws_root: Path | None) -> PresetSummary:
    """Load one preset and summarize it, capturing any load failure truthfully.

    Any load or validation error is caught and reported as an unloadable preset
    so one bad TOML never crashes the whole listing (a parse this broad is the
    point: the listing must survive an arbitrarily malformed preset).
    """
    from ...team.team_config import (
        authoring_capability,
        is_mock_preset,
        load_team_config,
    )

    is_mock = is_mock_preset(preset_id)
    try:
        tc = load_team_config(preset_id, workspace_root=ws_root)
    except Exception as exc:
        logger.warning("Team preset %s failed to load: %s", preset_id, exc)
        return PresetSummary(
            id=preset_id,
            loadable=False,
            unavailable_reason=str(exc)[:500] or type(exc).__name__,
            is_mock=is_mock,
        )
    return PresetSummary(
        id=tc.id,
        loadable=True,
        display_name=tc.display_name,
        description=tc.description,
        topology=tc.topology.type,
        worker_count=len(tc.workers),
        required_roles=[w.agent_id for w in tc.workers],
        authoring_capability=authoring_capability(tc.topology.type),
        is_mock=is_mock,
    )


# ---------------------------------------------------------------------------
# service-state
# ---------------------------------------------------------------------------


@router.get("/service", response_model=ServiceStateResponse)
async def service_state_endpoint(request: Request) -> ServiceStateResponse:
    """Return the health/doctor rollup for the resident gateway."""
    shared = assemble_health_status(app_state=request.app.state)
    ready = not (
        shared["circuit_breaker"] == "open"
        or shared["worker_status"] in {"down", "restarting"}
        or (shared["worker_spawned"] and not shared["worker_connected"])
    )
    return ServiceStateResponse(
        status="ok",
        ready=ready,
        worker_status=shared.get("worker_status"),
        worker_connected=shared.get("worker_connected"),
        circuit_breaker=shared.get("circuit_breaker"),
        database_backend=settings.resolved_database_backend,
        checkpoint_backend=settings.resolved_checkpoint_backend,
    )
