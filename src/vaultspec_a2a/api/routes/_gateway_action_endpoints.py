"""Run actions, provider catalog, presets, and service endpoints."""

import asyncio
import logging
import os
from dataclasses import dataclass
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

from ...control._permission_response_contract import (
    PermissionInput,
    PermissionRuntime,
)
from ...control._worker_health import worker_liveness
from ...control.cancel_service import CancelRuntime, cancel_thread
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
from ...control.message_service import send_followup_message
from ...control.permission_service import respond_to_permission
from ...control.run_start_policy import (
    required_role_ids,
)
from ...control.worker_status import WorkerConnectionStatus
from ...database import begin_write_transaction, get_db, get_permission_request
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
from ...thread.enums import TERMINAL_STATUSES, ControlActionResultStatus
from ...thread.idempotency import IDEMPOTENCY_KEY_MAX_LENGTH
from ...utils import package_version
from ...utils.coercion import coerce_object_mapping
from .._dispatch_refusals import (
    CODED_REFUSALS,
    DISPATCH_FAILURES,
    refusal_responses,
    refused_action,
    refused_cancel,
    refused_dispatch,
)
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
    RunCancelResponse,
    RunClarificationRespondRequest,
    RunClarificationRespondResponse,
    RunMessageRefusalResponse,
    RunMessageRequest,
    RunMessageResponse,
    RunPermissionRefusalResponse,
    RunPermissionRespondRequest,
    RunPermissionRespondResponse,
    ServiceStateResponse,
)
from ..schemas.provider_catalog import ProviderCatalogResponse
from ..workspace import require_existing_workspace_root
from .gateway import (
    _DEGRADED_CHECK_STATUSES,
    _bool_field,
    _catalog_records_within_budget,
    _int_field,
    _optional_enum,
    _string_field,
    admission_gate,
    router,
)

logger = logging.getLogger("vaultspec_a2a.api.routes.gateway")


@dataclass(frozen=True, slots=True)
class _ActionEndpointDependencies:
    """Injected resources shared by run action endpoints."""

    db: AsyncSession
    worker_client: httpx.AsyncClient
    circuit_breaker: Any
    worker_spawner: Any


def _get_action_endpoint_dependencies(
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> _ActionEndpointDependencies:
    """Group existing action service providers without changing their overrides."""
    return _ActionEndpointDependencies(
        db=db,
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
    )


@dataclass(frozen=True, slots=True)
class _ActionEndpointContext:
    """Request and idempotency context shared by the permission and cancel routes."""

    request: Request
    dependencies: _ActionEndpointDependencies
    idempotency_key: str | None


def _get_action_endpoint_context(
    request: Request,
    dependencies: _ActionEndpointDependencies = Depends(
        _get_action_endpoint_dependencies
    ),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> _ActionEndpointContext:
    """Collect request-scoped action inputs while retaining their route metadata."""
    return _ActionEndpointContext(
        request=request,
        dependencies=dependencies,
        idempotency_key=idempotency_key,
    )


@dataclass(frozen=True, slots=True)
class _MessageEndpointContext:
    """Request context for a follow-up turn, whose key the client must supply."""

    request: Request
    dependencies: _ActionEndpointDependencies
    idempotency_key: str


def _get_message_endpoint_context(
    request: Request,
    dependencies: _ActionEndpointDependencies = Depends(
        _get_action_endpoint_dependencies
    ),
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
        description=(
            "Opaque client-chosen key identifying this turn. Required: the "
            "gateway derives no default for this verb, because two deliberate "
            "identical continuations are two turns and a derived key would "
            "answer the second as a replay of the first."
        ),
    ),
) -> _MessageEndpointContext:
    """Collect follow-up inputs, refusing a request that names no key.

    The key is a parameter of THIS verb rather than of the shared action
    context: the other run actions address a durable thing that already exists
    - one permission request, one answer - and can derive a key from it, while
    a follow-up turn is only distinguishable from its own repeat by what the
    caller says.
    """
    return _MessageEndpointContext(
        request=request,
        dependencies=dependencies,
        idempotency_key=idempotency_key,
    )


@dataclass(frozen=True, slots=True)
class _ClarificationEndpointContext:
    """Request and injected services needed by clarification responses."""

    request: Request
    dependencies: _ActionEndpointDependencies
    checkpointer: Checkpointer


def _get_clarification_endpoint_context(
    request: Request,
    dependencies: _ActionEndpointDependencies = Depends(
        _get_action_endpoint_dependencies
    ),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> _ClarificationEndpointContext:
    """Collect clarification dependencies without changing provider wiring."""
    return _ClarificationEndpointContext(
        request=request,
        dependencies=dependencies,
        checkpointer=checkpointer,
    )


__all__ = ["_summarize_preset", "route_signature"]

# ---------------------------------------------------------------------------
# run-message
# ---------------------------------------------------------------------------


#: The served ``action_status`` of a turn whose work the run has finished.
#: A fresh admission never reports it; only a replay of a key whose turn has
#: already run does, which is what makes ``applied`` true on this verb.
_APPLIED_ACTION_STATUS = ControlActionResultStatus.APPLIED.value

# What a follow-up offer can be refused with. The verb queues the turn rather
# than dispatching it, so no worker or transport condition can reach it.
_FOLLOWUP_REFUSALS: frozenset[FailureType] = CODED_REFUSALS | {
    FailureType.NOT_FOUND,
    FailureType.NO_ACTIVE_PROJECT,
}


@router.post(
    "/runs/{run_id}/messages",
    status_code=202,
    response_model=RunMessageResponse,
    responses=refusal_responses(
        _FOLLOWUP_REFUSALS,
        {
            202: {
                "description": (
                    "The follow-up turn is queued behind the one the run is "
                    "executing. It holds a place in the run's queue and no write "
                    "authority; it reaches the worker when the current turn's "
                    "terminal checkpoint is proven. ``queue_position`` says where "
                    "it sits."
                ),
            },
            409: {
                "model": RunMessageRefusalResponse,
                "description": (
                    "The run cannot accept a follow-up turn. Nothing was reserved "
                    "and nothing was dispatched; the typed code names which "
                    "condition refused it."
                ),
            },
            # Restates the router's token refusal because naming a response here
            # replaces the router-wide description for this route.
            503: {
                "description": "Gateway service token is not configured.",
            },
        },
    ),
)
async def run_message_endpoint(
    run_id: PathSafeRunId,
    body: RunMessageRequest,
    context: _MessageEndpointContext = Depends(_get_message_endpoint_context),
) -> RunMessageResponse:
    """Queue a follow-up turn behind the one an existing run is executing.

    A run that is still executing a turn (SUBMITTED, RUNNING) takes the
    follow-up and answers 202 with ``action_status`` ``queued`` and the place
    it was given. The turn is reserved in the run's journal and NOTHING else:
    it binds no graph receipt, installs no writer and is not dispatched, which
    is what keeps the executing turn's own terminal from being refused as
    superseded. It becomes a dispatch only once that turn's terminal
    checkpoint is proven, and the run stays RUNNING across the boundary.

    A consumer must therefore not read a quiet turn boundary as completion: a
    run holding a queued continuation emits no terminal frame at the end of
    its first turn, and one at the end of its last.

    One continuation waits per run, and the service bounds the total. A second
    offer while one waits refuses ``queue_full``; nothing was reserved, and
    the caller may offer again once the waiting turn has run.

    Every other state still refuses, each for its own reason. A cancelling run
    is leaving, so a turn queued behind it would wait for a promotion that can
    never come. A parked run answers through its own typed respond verb, and a
    message here would start a turn that orphans the pause. A settled run is
    over; continuing it is a new run that names it as its predecessor.

    Run-start cannot carry this. A repeat run identifier there is a REPLAY - it
    answers with the original run and never adopts the new body - so without
    this verb the versioned surface can start a run and watch it, but never say
    anything further to it.

    The caller names the turn. ``Idempotency-Key`` is required here and has no
    server-derived default, because a default can only be derived from what the
    request already says - the run, the agent, the text - and two deliberate
    identical continuations are two turns, not one sent twice. Under a derived
    key the second was answered as a replay of the first and never ran. A
    request that names no key is refused before anything is read.

    Queued is not applied: the turn has not started, so a caller reconciles
    from the stream or run-status rather than from this response.
    """
    dependencies = context.dependencies
    result = await send_followup_message(
        db=dependencies.db,
        thread_id=run_id,
        content=body.content,
        agent_id=body.agent_id or DEFAULT_SUPERVISOR_ID,
        idempotency_key=context.idempotency_key,
    )

    if result.failure_type is not None:
        raise refused_dispatch(result.failure_type, result.error_detail)

    return RunMessageResponse(
        run_id=result.thread_id,
        action_status=result.action_status,
        applied=result.action_status == _APPLIED_ACTION_STATUS,
        action_id=result.action_id,
        idempotency_key=context.idempotency_key,
        queue_position=result.queue_position,
    )


# ---------------------------------------------------------------------------
# permission-respond
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/permissions/{request_id}/respond",
    response_model=RunPermissionRespondResponse,
    responses=refusal_responses(
        DISPATCH_FAILURES,
        {
            404: {
                "description": "No such run, or no such permission request on it.",
            },
            409: {
                "model": RunPermissionRefusalResponse,
                "description": (
                    "The answer was not taken. A worker that refused the dispatch "
                    "is reported with the typed refusal code every run action "
                    "shares; a request-state conflict carries a plain sentence. "
                    "Nothing was applied either way."
                ),
            },
            502: {
                "description": (
                    "The answer was accepted and retained but the worker could "
                    "not be reached or failed inside itself. Reconcile from "
                    "run-status."
                ),
            },
            # Restates the router's token refusal because naming a response
            # here replaces the router-wide description for this route.
            503: {
                "description": (
                    "Gateway service token is not configured, or the worker is "
                    "saturated or shut out by the failure breaker and the answer "
                    "was retained for retry."
                ),
            },
        },
    ),
)
async def run_permission_respond_endpoint(
    run_id: PathSafeRunId,
    request_id: str,
    body: RunPermissionRespondRequest,
    context: _ActionEndpointContext = Depends(_get_action_endpoint_context),
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
    dependencies = context.dependencies
    # The scoping read below opens the same transaction the service then writes
    # in, so it must hold the write lock from the start; a deferred read that
    # upgrades after a sibling commits is refused outright on SQLite.
    await begin_write_transaction(dependencies.db)
    permission = await get_permission_request(dependencies.db, request_id)
    if permission is None or permission.thread_id != run_id:
        await dependencies.db.rollback()
        raise HTTPException(
            status_code=404,
            detail=f"Permission request {request_id!r} not found for run {run_id!r}",
        )

    result = await respond_to_permission(
        db=dependencies.db,
        response=PermissionInput(
            request_id, body.option_id, context.idempotency_key, body.notes
        ),
        runtime=PermissionRuntime(
            dependencies.circuit_breaker,
            dependencies.worker_spawner,
            dependencies.worker_client,
            domain_config.graph_recursion_limit,
            trace_headers(),
        ),
    )

    if result.dispatched:
        worker_liveness(context.request.app.state).record_contact()
    if result.error_detail:
        raise refused_action(
            result.error_detail,
            guard_status=result.error_status_code,
            failure_type=result.failure_type,
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
    responses=refusal_responses(
        DISPATCH_FAILURES,
        {
            404: {
                "description": (
                    "No such run, or the run is not parked on this questionnaire."
                ),
            },
            409: {
                "description": (
                    "The resolution was not taken: a different one is already "
                    "accepted, the run is not active or cannot be confirmed to "
                    "have applied it, or the worker refused the dispatch with the "
                    "typed code every run action shares."
                ),
            },
        },
    ),
)
async def run_clarification_respond_endpoint(
    run_id: PathSafeRunId,
    request_id: str,
    body: RunClarificationRespondRequest,
    context: _ClarificationEndpointContext = Depends(
        _get_clarification_endpoint_context
    ),
) -> RunClarificationRespondResponse:
    """Resolve through the durable clarification lease service."""
    dependencies = context.dependencies
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
        dependencies.db,
        thread_id=run_id,
        request_id=request_id,
        resolution=resolution,
        runtime=ClarificationRuntime(
            context.checkpointer,
            dependencies.worker_client,
            dependencies.circuit_breaker,
            dependencies.worker_spawner,
            domain_config.graph_recursion_limit,
            trace_headers(),
        ),
    )
    if result.error_status_code is not None or result.failure_type is not None:
        raise refused_action(
            result.error_detail or "Clarification resolution failed",
            guard_status=result.error_status_code,
            failure_type=result.failure_type,
        )

    if result.dispatched:
        worker_liveness(context.request.app.state).record_contact()
    return RunClarificationRespondResponse(
        run_id=result.thread_id,
        request_id=result.request_id,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        idempotency_key=result.idempotency_key,
    )


# ---------------------------------------------------------------------------
# run-cancel
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunCancelResponse,
    responses=refusal_responses(
        DISPATCH_FAILURES,
        {
            409: {
                "description": (
                    "The run's state refuses cancellation - it settled some "
                    "other way, its accepted deadline expired, or its authority "
                    "changed - and no retry will change that; re-read "
                    "run-status. Cancelling a run that is already cancelled is "
                    "not refused."
                ),
            },
        },
    ),
)
async def run_cancel_endpoint(
    run_id: PathSafeRunId,
    context: _ActionEndpointContext = Depends(_get_action_endpoint_context),
) -> RunCancelResponse:
    """Cancel a run idempotently."""
    dependencies = context.dependencies
    result = await cancel_thread(
        db=dependencies.db,
        thread_id=run_id,
        idempotency_key=context.idempotency_key,
        runtime=CancelRuntime(
            dependencies.circuit_breaker,
            dependencies.worker_spawner,
            dependencies.worker_client,
            domain_config.graph_recursion_limit,
            trace_headers(),
        ),
    )

    refusal = refused_cancel(result)
    if refusal is not None:
        raise refusal

    if result.cancelled:
        worker_liveness(context.request.app.state).record_contact()

    # Cancellation is the drain's tool and is never itself admission-gated. When
    # a cancel settles the run terminally here (e.g. a submitted-but-undispatched
    # run), release it from the admission gate so a concurrent drain can quiesce;
    # a run that only reaches CANCELLING is deliberately left for the worker's
    # terminal event, which releases it in
    # ``control.event_handlers._handle_terminal_event``. Both sites can fire for
    # one run - the gate's release is an idempotent discard, so they cannot
    # corrupt the active set.
    if result.thread_status in TERMINAL_STATUSES:
        await admission_gate(context.request.app).release(result.thread_id)

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
    canonical = str(require_existing_workspace_root(workspace_root))
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
    ws_root = (
        require_existing_workspace_root(workspace_root) if workspace_root else None
    )
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


def _service_dependency_readiness(
    checks: dict[str, object],
) -> tuple[bool, bool, bool]:
    return (
        _service_check_ready(checks, "database"),
        _service_check_ready(checks, "checkpoint"),
        _service_check_ready(checks, "worker"),
    )


def _service_check_ready(checks: dict[str, object], name: str) -> bool:
    check = coerce_object_mapping(checks.get(name)) or {}
    return _string_field(check, "status") == "ok"


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
    from ...control._worker_health import GATEWAY_LIFETIME_ID

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
    database_ready, checkpoint_ready, worker_ready = _service_dependency_readiness(
        checks
    )
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
        service_version=package_version(),
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
        probe_elapsed_ms=_int_field(full, "probe_elapsed_ms"),
        degraded_reasons=degraded_reasons,
        routes=route_signature(request.app),
        readiness=readiness,
    )
