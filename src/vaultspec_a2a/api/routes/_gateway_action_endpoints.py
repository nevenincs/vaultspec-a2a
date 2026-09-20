"""Run actions, provider catalog, presets, and service endpoints."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.clarification_service import (
    ClarificationRuntime,
    respond_to_clarification,
)
from ...control.config import settings
from ...control.health import (
    FullHealthRuntime,
    assemble_desktop_readiness,
    build_full_health,
    probe_engine_discovery_freshness,
)
from ...control.message_service import MessageResult, send_followup_message
from ...control.permission_service import (
    PermissionInput,
    PermissionRuntime,
    respond_to_permission,
)
from ...control.run_start_policy import (
    required_role_ids,
)
from ...control.worker_management import worker_liveness
from ...control.worker_status import WorkerConnectionStatus
from ...database import (
    get_db,
    get_permission_request,
    normalize_workspace_identity,
)
from ...database.checkpoints import Checkpointer
from ...domain_config import domain_config
from ...providers.provider_catalog_service import (
    ProviderCatalogScopeCapacityError,
)
from ...streaming.aggregator import EventAggregator
from ...team.preset_origin import PresetOrigin
from ...thread.clarification import (
    ClarificationAnswers,
    ClarificationContinuation,
    ClarificationDecline,
    ClarificationResolution,
)
from ...thread.constants import (
    DEFAULT_SUPERVISOR_ID,
    MAX_WORKSPACE_ROOT_LENGTH,
)
from ...thread.dispatch_policy import FailureType
from ...thread.enums import (
    ThreadStatus,
)
from ...utils.coercion import coerce_object_mapping
from .._utils import trace_headers
from ..dependencies import (
    get_checkpointer,
    get_circuit_breaker,
    get_services,
    get_worker_client,
    get_worker_spawner,
)
from ..schemas.gateway import (
    PathSafeRunId,
    PresetsListResponse,
    PresetSummary,
    RunClarificationRespondRequest,
    RunClarificationRespondResponse,
    RunMessageRequest,
    RunMessageResponse,
    RunPermissionRespondRequest,
    RunPermissionRespondResponse,
    ServiceStateResponse,
)
from ..schemas.provider_catalog import ProviderCatalogResponse
from .gateway import (
    _DEGRADED_CHECK_STATUSES,
    _bool_field,
    _catalog_records_within_budget,
    _optional_enum,
    _string_field,
    router,
)

logger = logging.getLogger("vaultspec_a2a.api.routes.gateway")

__all__ = ["_summarize_preset", "route_signature"]

# ---------------------------------------------------------------------------
# run-message
# ---------------------------------------------------------------------------


async def _raise_for_message_dispatch_failure(
    request: Request, result: MessageResult
) -> None:
    if result.failure_type is None:
        return
    # A failed follow-up can settle without a terminal worker event.
    if result.thread_status == ThreadStatus.FAILED.value:
        drain_gate = getattr(request.app.state, "drain_gate", None)
        if drain_gate is not None:
            await drain_gate.release(result.thread_id)
    if result.failure_type in (FailureType.CIRCUIT_OPEN, FailureType.AT_CAPACITY):
        raise HTTPException(status_code=503, detail=result.error_detail)
    raise HTTPException(status_code=502, detail=result.error_detail)


@router.post(
    "/runs/{run_id}/messages",
    status_code=202,
    response_model=RunMessageResponse,
)
async def run_message_endpoint(
    run_id: PathSafeRunId,
    body: RunMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunMessageResponse:
    """Send a follow-up turn into an existing run.

    Run-start cannot carry this. A repeat run identifier there is a REPLAY - it
    answers with the original run and never adopts the new body - so without
    this verb the versioned surface can start a run and watch it, but never say
    anything further to it.

    Accepted is not applied: the turn is handed to the worker and execution
    continues asynchronously, so a caller reconciles from the stream or
    run-status rather than from this response.
    """
    result = await send_followup_message(
        db=db,
        thread_id=run_id,
        content=body.content,
        agent_id=body.agent_id or DEFAULT_SUPERVISOR_ID,
        idempotency_key=idempotency_key,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )

    if result.failure_type == FailureType.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Run not found")
    if result.failure_type == FailureType.NO_ACTIVE_PROJECT:
        # Same status the run-creation seam returns for the same missing
        # invariant, so one rule reads identically at both entry points.
        raise HTTPException(status_code=422, detail=result.error_detail)
    if result.failure_type in (
        FailureType.INPUT_REQUIRED,
        FailureType.TERMINAL,
        FailureType.CONFLICT,
        FailureType.INCOMPATIBLE_STATE,
    ):
        raise HTTPException(status_code=409, detail=result.error_detail)

    if result.dispatched:
        worker_liveness(request.app.state).record_contact()

    await _raise_for_message_dispatch_failure(request, result)

    return RunMessageResponse(
        run_id=result.thread_id,
        action_status=(
            "accepted_not_applied" if result.dispatched else result.thread_status
        ),
        action_id=result.action_id,
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# permission-respond
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/permissions/{request_id}/respond",
    response_model=RunPermissionRespondResponse,
)
async def run_permission_respond_endpoint(
    run_id: PathSafeRunId,
    request_id: str,
    body: RunPermissionRespondRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunPermissionRespondResponse:
    """Answer a permission request the run raised on its progress stream.

    The versioned surface already POSES this question - ``permission_request``
    is an enumerated frame on run-stream - and this is where the answer returns.
    Without it the only answering channel is the transition surface, so retiring
    that surface would strand every paused run.

    The verb adds no state machine of its own: it is a versioned projection of
    the same answer path, so at-most-once behaviour comes from there. Answering
    twice replays the stored outcome rather than acting again, an answer arriving
    after the request was applied reports the duplicate without re-dispatching,
    and a superseded or expired request is refused with a journaled rejection
    that replays identically.

    Scoping matters as much as the answer. The request is resolved and checked
    against the run in the path BEFORE anything acts on it, so a guessed request
    id cannot be used to answer another run's question - and because that check
    precedes the service call, a mismatch has no effect at all rather than being
    detected after the fact.
    """
    permission = await get_permission_request(db, request_id)
    if permission is None or permission.thread_id != run_id:
        raise HTTPException(
            status_code=404,
            detail=f"Permission request {request_id!r} not found for run {run_id!r}",
        )

    result = await respond_to_permission(
        db=db,
        response=PermissionInput(
            request_id, body.option_id, idempotency_key, body.notes
        ),
        runtime=PermissionRuntime(
            circuit_breaker,
            worker_spawner,
            worker_client,
            domain_config.graph_recursion_limit,
            trace_headers(),
        ),
    )

    if result.dispatched:
        worker_liveness(request.app.state).record_contact()
    if result.circuit_open:
        raise HTTPException(status_code=503, detail=result.error_detail)
    if result.error_detail:
        raise HTTPException(
            status_code=result.error_status_code or 500,
            detail=result.error_detail,
        )

    return RunPermissionRespondResponse(
        run_id=result.thread_id,
        request_id=result.request_id,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        approval_status=result.approval_status,
        idempotency_key=result.idempotency_key,
    )


# ---------------------------------------------------------------------------
# clarification-respond
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/clarifications/{request_id}/respond",
    response_model=RunClarificationRespondResponse,
)
async def run_clarification_respond_endpoint(
    run_id: PathSafeRunId,
    request_id: str,
    body: RunClarificationRespondRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> RunClarificationRespondResponse:
    """Resolve through the durable clarification lease service."""
    resolution: ClarificationResolution
    if body.answers is not None:
        resolution = ClarificationAnswers(
            request_id=request_id, answers=dict(body.answers)
        )
    elif body.decline is not None:
        resolution = ClarificationDecline(request_id=request_id)
    else:
        prompt = body.prompt
        if prompt is None:
            raise RuntimeError("validated clarification resolution is missing")
        resolution = ClarificationContinuation(
            request_id=request_id,
            prompt=prompt,
        )

    result = await respond_to_clarification(
        db,
        thread_id=run_id,
        request_id=request_id,
        resolution=resolution,
        runtime=ClarificationRuntime(
            checkpointer,
            worker_client,
            circuit_breaker,
            worker_spawner,
            domain_config.graph_recursion_limit,
            trace_headers(),
        ),
    )
    if result.error_status_code is not None:
        raise HTTPException(
            status_code=result.error_status_code,
            detail=result.error_detail or "Clarification resolution failed",
        )

    if result.dispatched:
        worker_liveness(request.app.state).record_contact()
    return RunClarificationRespondResponse(
        run_id=result.thread_id,
        request_id=result.request_id,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        idempotency_key=result.idempotency_key,
    )


# ---------------------------------------------------------------------------
# provider-catalog
# ---------------------------------------------------------------------------


@router.get("/provider-catalog", response_model=ProviderCatalogResponse)
async def provider_catalog_endpoint(
    request: Request,
    workspace_root: str = Query(min_length=1, max_length=MAX_WORKSPACE_ROOT_LENGTH),
) -> ProviderCatalogResponse:
    """Serve prompt-free, execution-lane-specific catalogs for one workspace."""
    supplied_keys = set(request.query_params.keys())
    if (
        supplied_keys != {"workspace_root"}
        or len(request.query_params.getlist("workspace_root")) != 1
    ):
        raise HTTPException(
            status_code=422,
            detail="provider-catalog accepts exactly one workspace_root query value",
        )
    requested = Path(workspace_root)
    if not requested.is_absolute():
        raise HTTPException(
            status_code=422, detail="workspace_root must be an absolute directory"
        )
    canonical = normalize_workspace_identity(workspace_root)
    if len(canonical) > MAX_WORKSPACE_ROOT_LENGTH or not Path(canonical).is_dir():
        raise HTTPException(
            status_code=422,
            detail="workspace_root must identify an existing directory",
        )
    try:
        records = await _catalog_records_within_budget(request.app, canonical)
    except ProviderCatalogScopeCapacityError:
        raise HTTPException(
            status_code=503,
            detail="provider catalog workspace capacity is temporarily busy",
        ) from None
    return ProviderCatalogResponse.from_records(records)


# ---------------------------------------------------------------------------
# presets-list
# ---------------------------------------------------------------------------


@router.get("/presets", response_model=PresetsListResponse)
async def presets_list_endpoint(
    workspace_root: str | None = Query(
        default=None, max_length=MAX_WORKSPACE_ROOT_LENGTH
    ),
) -> PresetsListResponse:
    """List team presets truthfully, marking each loadable or unloadable.

    Resolution uses the requested workspace context so workspace-local presets
    are listed alongside the bundled set. A single preset that fails to load or
    validate is reported with ``loadable=False`` and a reason rather than
    omitted or allowed to crash the whole listing. File I/O runs off the event
    loop.
    """
    ws_root = Path(workspace_root) if workspace_root else None
    presets = await asyncio.to_thread(_build_preset_summaries, ws_root)
    return PresetsListResponse(presets=presets)


def _build_preset_summaries(ws_root: Path | None) -> list[PresetSummary]:
    """Summarize every discoverable preset."""
    from ...team.team_config import discover_team_preset_ids

    return [
        _summarize_preset(preset_id, ws_root)
        for preset_id in sorted(discover_team_preset_ids(ws_root))
    ]


def _safe_load_reason(exc: Exception) -> str:
    """Return a path-free unavailable reason for a preset load/validation failure.

    Raw exception strings (TOML parse errors, config errors) can embed the
    workspace/preset filesystem path; the served reason states the failure
    category without any path so discovery never leaks local paths.
    """

    from ...thread.errors import ConfigError, TeamConfigNotFoundError

    if isinstance(exc, TeamConfigNotFoundError):
        return "preset not found"
    if isinstance(exc, ValidationError):
        return "preset failed schema validation"
    if isinstance(exc, ConfigError):
        return "preset TOML is invalid or missing its [team] section"
    return f"preset failed to load ({type(exc).__name__})"


def _preset_origin(
    preset_id: str, ws_root: Path | None, *, is_mock: bool
) -> PresetOrigin:
    """Classify a preset's origin: test_mock, workspace, or bundled."""
    if is_mock:
        return PresetOrigin.TEST_MOCK
    if ws_root is not None:
        workspace_toml = ws_root / ".vaultspec" / "teams" / f"{preset_id}.toml"
        if workspace_toml.is_file():
            return PresetOrigin.WORKSPACE
    return PresetOrigin.BUNDLED


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
        supported_capabilities,
    )

    is_mock = is_mock_preset(preset_id)
    try:
        tc = load_team_config(preset_id, workspace_root=ws_root)
    except Exception as exc:
        logger.warning("Team preset %s failed to load: %s", preset_id, exc)
        return PresetSummary(
            id=preset_id,
            loadable=False,
            unavailable_reason=_safe_load_reason(exc),
            is_mock=is_mock,
            origin=_preset_origin(preset_id, ws_root, is_mock=is_mock),
        )
    return PresetSummary(
        id=tc.id,
        loadable=True,
        display_name=tc.display_name,
        description=tc.description,
        topology=tc.topology.type,
        worker_count=len(tc.workers),
        # The same function run-start REFUSES against, not a second derivation of
        # it: discovery advertises the roles a caller must mint, and a caller that
        # mints exactly what it was told must never then be refused for missing
        # one. Two independent list comprehensions agreeing today is not that
        # guarantee - it is the guarantee's absence, and the failure it would
        # produce lands before the graph ever runs, where nothing downstream can
        # observe it.
        required_roles=required_role_ids(tc),
        authoring_capability=authoring_capability(tc),
        is_mock=is_mock,
        origin=_preset_origin(preset_id, ws_root, is_mock=is_mock),
        supported_capabilities=supported_capabilities(tc.topology.type),
    )


# ---------------------------------------------------------------------------
# service-state
# ---------------------------------------------------------------------------


def route_signature(app: FastAPI) -> list[str]:
    """Return a sorted ``"METHOD path"`` signature from *app*'s OpenAPI schema.

    FastAPI's OpenAPI generation is the one place that correctly flattens the
    (internal, lazily-resolved) route table, so it is used here as the
    public, stable source of truth instead of walking ``app.routes``
    directly. Shared between the live endpoint (this process's app) and the
    doctor CLI's locally-constructed expectation (``create_app()``) so the
    two are comparable: a resident process started before a route landed
    serves a signature missing that entry - detectable without depending on
    a version string editable installs don't bump per-commit.
    """
    paths = app.openapi().get("paths", {})
    return sorted(
        f"{method.upper()} {path}"
        for path, operations in paths.items()
        for method in operations
    )


def _service_degraded_reasons(checks: dict[str, object]) -> list[str]:
    reasons: list[str] = []
    for name, check_value in checks.items():
        check = coerce_object_mapping(check_value)
        if check is None:
            continue
        status_value = _string_field(check, "status")
        if status_value in _DEGRADED_CHECK_STATUSES:
            detail = _string_field(check, "detail") or status_value
            reasons.append(f"{name}: {detail}")
    return reasons


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
    # Local import matching this module's convention for control-layer symbols.
    # The constant is minted once per gateway process, so this is the very
    # identity the spawner stamps into the workers it starts.
    from ...control.worker_management import GATEWAY_LIFETIME_ID

    db, _aggregator, _checkpointer, worker_client = services
    full = await build_full_health(
        db=db,
        runtime=FullHealthRuntime(
            worker_client=worker_client,
            circuit_breaker=circuit_breaker,
            worker_spawner=worker_spawner,
        ),
        app_state=request.app.state,
        # This surface is attach-authenticated, which is the only place the
        # pairing identity may be disclosed; the unauthenticated health endpoint
        # serves the same payload and must not carry it.
        include_pairing=True,
    )
    checks = coerce_object_mapping(full.get("checks")) or {}
    database_check = coerce_object_mapping(checks.get("database")) or {}
    checkpoint_check = coerce_object_mapping(checks.get("checkpoint")) or {}
    worker_check = coerce_object_mapping(checks.get("worker")) or {}
    database_ready = _string_field(database_check, "status") == "ok"
    checkpoint_ready = _string_field(checkpoint_check, "status") == "ok"
    worker_ready = _string_field(worker_check, "status") == "ok"
    can_accept_run = full["status"] == "ok"

    if not database_ready:
        status = "unavailable"
    elif not can_accept_run:
        status = "degraded"
    else:
        status = "ready"

    # The separated readiness facts come from the one readiness authority, fed the
    # live database and worker probe verdicts just computed, so service-state and
    # the liveness surface never compute readiness twice. This is also the
    # projection a discovery contender probes to validate readiness before attach.
    readiness = assemble_desktop_readiness(
        app_state=request.app.state,
        database_ready=database_ready,
        worker_probe_ready=worker_ready,
    )

    # Only genuine failure statuses degrade readiness; informational checks such
    # as worker_spawned ("yes"/"no") or worker_stderr_log ("configured") are not
    # degradation signals.
    degraded_reasons = _service_degraded_reasons(checks)

    return ServiceStateResponse(
        service_version=_service_version(),
        status=status,
        alive=True,
        ready=can_accept_run,
        can_accept_run=can_accept_run,
        gateway_pid=os.getpid(),
        # Pairing identity, served so a consumer never has to infer it from
        # addressing facts: this gateway's own incarnation identity, plus what
        # the worker reported about which incarnation spawned it. A mismatch
        # means the worker belongs to another gateway; both blank mean it was
        # not gateway-spawned at all.
        gateway_lifetime_id=GATEWAY_LIFETIME_ID,
        worker_paired_gateway_lifetime=_string_field(
            full, "worker_paired_gateway_lifetime"
        ),
        worker_generation=_string_field(full, "worker_reported_generation"),
        worker_status=_optional_enum(
            WorkerConnectionStatus, _string_field(full, "worker_status")
        ),
        worker_connected=_bool_field(full, "worker_connected"),
        circuit_breaker=_string_field(full, "circuit_breaker"),
        database_backend=settings.resolved_database_backend,
        checkpoint_backend=settings.resolved_checkpoint_backend,
        database_ready=database_ready,
        checkpoint_ready=checkpoint_ready,
        worker_ready=worker_ready,
        authoring_backend_reachable=probe_engine_discovery_freshness(),
        active_run_capacity=domain_config.max_concurrent_threads,
        degraded_reasons=degraded_reasons,
        routes=route_signature(request.app),
        readiness=readiness,
    )


def _service_version() -> str:
    """Return the installed a2a distribution version, or 'unknown'."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("vaultspec-a2a")
    except PackageNotFoundError:
        return "unknown"
