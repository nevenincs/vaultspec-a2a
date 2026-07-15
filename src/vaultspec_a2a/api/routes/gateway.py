"""The versioned five-verb gateway surface (ADR R6).

Mounts ``run-start``, ``run-status``, ``run-cancel``, ``presets-list``, and
``service-state`` under ``/v1`` as the engine-facing edge. Each verb reshapes an
existing service rather than reinventing it, so there is a single code path: the
richer internal ``/api`` surface and these verbs call the same services beneath.
"""

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.cancel_service import cancel_thread
from ...control.config import settings
from ...control.health import build_full_health, probe_engine_discovery_freshness
from ...control.run_start_policy import evaluate_run_start_eligibility
from ...control.thread_service import (
    ThreadCreationRequest,
    create_and_dispatch_thread,
    generate_thread_id,
    process_metadata,
)
from ...control.thread_state_service import (
    build_thread_state,
    project_semantic_phase,
    read_run_authoring_ids,
    read_run_semantic_context,
)
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

# Health-check statuses that represent a genuine dependency failure (as opposed
# to informational states like worker_spawned="yes"); these populate
# service-state degraded_reasons.
_DEGRADED_CHECK_STATUSES: frozenset[str] = frozenset(
    {"error", "open", "down", "restarting", "half_open", "timeout"}
)


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


def _active_role(next_nodes: list[str], agents: list[Any]) -> str | None:
    """Active position in product ROLE vocabulary, never a node name (PW4).

    Maps the checkpoint's active node to the role of the matching agent (its
    node is named by its agent id, minus the ADR-020 ``mount_`` prefix). Internal
    orchestration and gate nodes have no matching agent, so they surface as
    ``None`` rather than leaking an internal LangGraph node name into the product
    status contract; per-role ``state`` and ``pause_cause`` carry the rest.
    """
    role_by_id = {agent.agent_id: agent.role for agent in agents}
    for node in next_nodes:
        if not node or node == "__end__":
            continue
        role = role_by_id.get(node.removeprefix("mount_"))
        if role:
            return role
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
    semantic = await read_run_semantic_context(checkpointer, run_id)
    semantic_phase = project_semantic_phase(
        status=snapshot.status,
        next_nodes=snapshot.next_nodes,
        repair_status=snapshot.repair_status,
    )

    return RunStatusResponse(
        run_id=snapshot.thread_id,
        status=ThreadStatus(snapshot.status),
        semantic_phase=semantic_phase,
        feature_tag=semantic.feature_tag,
        authoring_session_id=semantic.authoring_session_id,
        topology=TopologyPosition(
            team_preset=team_preset,
            active_agent=_active_role(snapshot.next_nodes, snapshot.agents),
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
async def service_state_endpoint(
    request: Request,
    services: tuple[
        AsyncSession, EventAggregator, Checkpointer, httpx.AsyncClient
    ] = Depends(get_services),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> ServiceStateResponse:
    """Return truthful, probe-backed readiness for the resident gateway.

    Runs the real dependency probes (database, checkpoint, worker) rather than
    reporting a hardcoded status, and separates process-alive from
    can-accept-run. Engine authoring-backend reachability is reported from
    non-blocking discovery-file freshness.
    """
    db, _aggregator, _checkpointer, worker_client = services
    full = await build_full_health(
        db=db,
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        app_state=request.app.state,
    )
    checks: dict[str, Any] = full["checks"]
    database_ready = checks.get("database", {}).get("status") == "ok"
    checkpoint_ready = checks.get("checkpoint", {}).get("status") == "ok"
    worker_ready = checks.get("worker", {}).get("status") == "ok"
    can_accept_run = full["status"] == "ok"

    if not database_ready:
        status = "unavailable"
    elif not can_accept_run:
        status = "degraded"
    else:
        status = "ready"

    # Only genuine failure statuses degrade readiness; informational checks such
    # as worker_spawned ("yes"/"no") or worker_stderr_log ("configured") are not
    # degradation signals.
    degraded_reasons = [
        f"{name}: {check.get('detail', check.get('status'))}"
        for name, check in checks.items()
        if isinstance(check, dict) and check.get("status") in _DEGRADED_CHECK_STATUSES
    ]

    return ServiceStateResponse(
        service_version=_service_version(),
        status=status,
        alive=True,
        ready=can_accept_run,
        can_accept_run=can_accept_run,
        gateway_pid=os.getpid(),
        worker_status=full.get("worker_status"),
        worker_connected=full.get("worker_connected"),
        circuit_breaker=full.get("circuit_breaker"),
        database_backend=settings.resolved_database_backend,
        checkpoint_backend=settings.resolved_checkpoint_backend,
        database_ready=database_ready,
        checkpoint_ready=checkpoint_ready,
        worker_ready=worker_ready,
        authoring_backend_reachable=probe_engine_discovery_freshness(),
        active_run_capacity=domain_config.max_concurrent_threads,
        degraded_reasons=degraded_reasons,
    )


def _service_version() -> str:
    """Return the installed a2a distribution version, or 'unknown'."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("vaultspec-a2a")
    except PackageNotFoundError:
        return "unknown"
