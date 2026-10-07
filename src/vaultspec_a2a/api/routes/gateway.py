"""The versioned gateway surface.

Mounts the run, preset, and service verbs under ``/v1`` as the engine-facing
edge, including bounded discovery and the droppable ``run-stream`` companion to
the authoritative status snapshot. Each verb reshapes an existing service
rather than reinventing it, so there is a single code path: the richer internal
``/api`` surface and these verbs call the same services beneath.

Run start composes :mod:`vaultspec_a2a.control.admission` and
:mod:`vaultspec_a2a.control.health` into ``start``, readiness-gated ``prepare``,
exact ``commit``, and uncommitted-reservation ``release`` stages. A committed
run persists its non-secret lease identifier and exact replay digest. Dispatch
exactly once under that replay contract is not end-to-end exactly-once delivery,
and a lease identifier is never a bearer credential.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
)
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from ...team import TeamConfig

from ...control.admission import AdmissionBroker, AdmissionReadiness
from ...control.config import settings
from ...control.drain import DrainGate
from ...control.execution_authority import (
    read_frozen_team_selection,
    record_frozen_team_selection,
)
from ...control.health import (
    assemble_desktop_readiness,
)
from ...control.run_start_policy import (
    required_role_ids,
)
from ...domain_config import domain_config
from ...providers.provider_catalog import (
    ControlSelection,
    ProviderRecord,
    SelectionReference,
)
from ...providers.provider_catalog_service import (
    ProviderCatalogScopeCapacityError,
    ProviderCatalogService,
)
from ...providers.team_selection import (
    FrozenTeamSelection,
    TeamSelectionError,
    freeze_team_selection,
    normalize_replay_selection,
)
from ...thread.constants import RUN_ID_PATTERN
from ...utils.coercion import coerce_object_mapping
from ..auth import authenticate_request
from ..run_admission import (
    replay_digest_matches,
    request_digest,
)
from ..schemas.gateway import (
    FrozenTeamAssignmentSummary,
    ProviderCatalogSelection,
    RunStartRequest,
)
from ..workspace import require_existing_workspace_root

router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(authenticate_request)],
    # Every route here is behind the attach gate, so both refusals are properties
    # of the router rather than of any one verb. They were absent from the
    # published contract, which documented only success and validation failure -
    # a client generated from it modeled 401 as an unexpected transport error.
    responses={
        401: {"description": "Missing or invalid gateway service token."},
        503: {"description": "Gateway service token is not configured."},
    },
)
logger = logging.getLogger(__name__)

__all__ = [
    "_DEGRADED_CHECK_STATUSES",
    "_body_with_frozen_selection",
    "_bool_field",
    "_canonical_replay_body",
    "_catalog_records_within_budget",
    "_int_field",
    "_load_preset_or_refuse",
    "_modern_frozen_disclosure",
    "_optional_enum",
    "_persist_lease",
    "_persist_request_digest",
    "_persist_team_selection",
    "_persisted_lease_binding",
    "_persisted_lease_id",
    "_prepare_workspace_root",
    "_probe_admission_readiness",
    "_probe_harness",
    "_release_binding_digest",
    "_release_ineligible_reservation",
    "_replay_identity_or_conflict",
    "_string_field",
    "_validate_and_freeze_selection_or_refuse",
    "router",
]

# Health-check statuses that represent a genuine dependency failure (as opposed
# to informational states like worker_spawned="yes"); these populate
# service-state degraded_reasons.
_DEGRADED_CHECK_STATUSES: frozenset[str] = frozenset(
    {"error", "open", "down", "restarting", "half_open", "timeout"}
)


def provider_catalog_service(app: FastAPI) -> ProviderCatalogService:
    """Return the process-wide bounded provider-catalog service."""
    service = getattr(app.state, "provider_catalog_service", None)
    if service is None:
        service = ProviderCatalogService()
        app.state.provider_catalog_service = service
    return service


def _metadata_object(metadata_json: str | None) -> dict[str, object] | None:
    """Decode durable metadata only when it is a JSON object."""
    if not metadata_json:
        return None
    try:
        decoded: object = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return coerce_object_mapping(decoded)


def _string_field(record: dict[str, object], field: str) -> str | None:
    value = record.get(field)
    return value if isinstance(value, str) else None


def _bool_field(record: dict[str, object], field: str) -> bool | None:
    value = record.get(field)
    return value if isinstance(value, bool) else None


def _int_field(record: dict[str, object], field: str) -> int | None:
    """Read an integer diagnostic, rejecting the bool that ``int`` would admit."""
    value = record.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_enum[StrEnumT: StrEnum](
    enum_cls: type[StrEnumT],
    value: str | None,
) -> StrEnumT | None:
    """Coerce a durable string field into its declared enum member, when present."""
    return None if value is None else enum_cls(value)


def admission_gate(app: FastAPI) -> DrainGate:
    """Return the process-wide run-admission drain gate, creating it once.

    One :class:`DrainGate` per gateway process, seated on ``app.state`` so the
    run verbs here and the administrative stop path (gateway shutdown /
    receipt-bound admin shutdown, wired where those handlers live) share the
    single authority: run-start admits against it, and the stop path closes
    admission and drains it before bounded cancellation. Get-or-create is atomic
    on the single event loop - there is no await between the read and the store.
    """
    gate = getattr(app.state, "drain_gate", None)
    if gate is None:
        gate = DrainGate()
        app.state.drain_gate = gate
    return gate


def admission_broker(app: FastAPI) -> AdmissionBroker:
    """Return the process-wide run-admission reservation broker, creating it once.

    One :class:`AdmissionBroker` per gateway process, seated on ``app.state``
    beside the drain gate. The prepare and commit stages of run-start share it: a
    reservation is bounded by the configured concurrent-run capacity. Get-or-create
    is atomic on the single event loop - there is no await between read and store.
    """
    broker = getattr(app.state, "admission_broker", None)
    if broker is None:
        broker = AdmissionBroker(
            max_reservations=domain_config.max_concurrent_threads,
            reservation_ttl_seconds=domain_config.admission_reservation_ttl_seconds,
        )
        app.state.admission_broker = broker
    return broker


def _admission_readiness(
    app_state: Any,
    *,
    worker_probe_ready: bool | None = None,
    worker_adoptable: bool | None = None,
) -> AdmissionReadiness:
    """Project the seated desktop readiness facts into an admission-readiness view.

    Reads the single readiness authority (``assemble_desktop_readiness``) over the
    seated worker and database state - the cheap, non-blocking surface - so
    prepare and commit gate on the same run-admission verdict the readiness model
    and service-state verb serve, never a second computation.
    """
    readiness = assemble_desktop_readiness(
        app_state=app_state,
        worker_probe_ready=worker_probe_ready,
        worker_adoptable=worker_adoptable,
    )
    return AdmissionReadiness(
        worker_state=readiness.worker_state,
        provider_eligibility=readiness.provider_eligibility,
        eligible_providers=tuple(readiness.eligible_providers),
        run_admission=readiness.run_admission,
        reasons=tuple(readiness.reasons),
    )


async def _probe_admission_readiness(
    app_state: Any, worker_client: httpx.AsyncClient
) -> AdmissionReadiness:
    from ...control._worker_health import probe_worker_health, worker_ready_and_ours

    probe = await probe_worker_health(settings.worker_url, client=worker_client)
    reachable = probe.healthy
    # An indeterminate probe (the worker did not answer inside the budget) is not
    # an observation of absence, so it must not be reported as one: pass no live
    # verdict and let the readiness authority fall back to the watchdog's seated
    # worker state. A worker compiling a graph for an already-admitted run is
    # unresponsive for seconds, and refusing an unrelated admission on that basis
    # made every concurrent run-start fail while the first one booted.
    probe_verdict: bool | None = None if probe.indeterminate else reachable
    # Reachability and provenance are different questions, and admission needs
    # both: "some process holds this port" is exactly what a squatting orphan
    # satisfies. Only asked when the port answered at all, so the refusal path
    # costs nothing extra.
    #
    # The generation must come from the spawner that issued it. It is the highest
    # generation this gateway has minted, and a worker reporting a HIGHER one
    # classifies as unidentified - so defaulting it to zero here would disown our
    # own restarted worker on its own admission path.
    spawner = getattr(app_state, "worker_spawner", None)
    generation = getattr(spawner, "generation", 0)
    adoptable: bool | None
    if probe.indeterminate:
        # Provenance is unknown for the same reason health is; the promotion this
        # feeds requires an affirmative True, so None neither promotes nor demotes.
        adoptable = None
    else:
        adoptable = reachable and await worker_ready_and_ours(
            settings.worker_url, current_generation=generation
        )
    return _admission_readiness(
        app_state, worker_probe_ready=probe_verdict, worker_adoptable=adoptable
    )


def _prepare_workspace_root(body: RunStartRequest) -> Path | None:
    """Resolve the preset-loading workspace for a run-start request, or ``None``.

    Resolving it mints nothing: a prepare never mints a workspace, and a new run
    mints its project afterwards, in the same canonical spelling. It only gives
    the request a workspace context to resolve a workspace-local preset. When the
    request metadata names an absolute workspace root it is used, otherwise the
    bundled preset set is resolved (``None``).
    """
    metadata = body.metadata
    workspace_root = getattr(metadata, "workspace_root", None) if metadata else None
    if not workspace_root:
        return None
    return require_existing_workspace_root(workspace_root)


def _release_binding_digest(body: RunStartRequest) -> str:
    """Bind release to the raw prepared request, not canonical commit policy."""
    return request_digest(body, prepared=True)


async def _release_ineligible_reservation(
    broker: AdmissionBroker, reservation_id: str, canonical_body: RunStartRequest
) -> bool:
    """Release a refused commit under its canonical prepared identity."""
    return await broker.release_failed_commit(
        reservation_id,
        binding_digest=request_digest(canonical_body, prepared=True),
    )


def _selection_reference(value: ProviderCatalogSelection) -> SelectionReference:
    """Convert the bounded wire map into the canonical provider-domain type."""
    return SelectionReference(
        schema_version=value.schema_version,
        provider_id=value.provider_id,
        execution_mode=value.execution_mode,
        catalog_revision=value.catalog_revision,
        entry_id=value.entry_id,
        controls=tuple(
            ControlSelection(control_id=control_id, option_id=option_id)
            for control_id, option_id in sorted(value.controls.items())
        ),
    )


def _wire_reference(reference: SelectionReference) -> ProviderCatalogSelection:
    """Render a normalized domain reference into the canonical request wire."""
    return ProviderCatalogSelection(
        schema_version=1,
        provider_id=reference.provider_id,
        execution_mode=reference.execution_mode,
        catalog_revision=reference.catalog_revision,
        entry_id=reference.entry_id,
        controls={item.control_id: item.option_id for item in reference.controls},
    )


def _wire_selection(value: Any) -> ProviderCatalogSelection:
    """Render a normalized frozen lane back into the canonical request wire."""
    return _wire_reference(value.reference)


def _body_with_frozen_selection(
    body: RunStartRequest, frozen: FrozenTeamSelection
) -> RunStartRequest:
    """Return the request with authoritative catalog defaults made explicit."""
    return body.model_copy(
        update={
            "selection": _wire_selection(frozen.selection),
            "overrides": {
                role: _wire_selection(value) for role, value in frozen.overrides.items()
            },
            "fallbacks": [_wire_selection(value) for value in frozen.fallbacks],
        }
    )


def _canonical_replay_body(
    metadata_json: str | None, body: RunStartRequest
) -> RunStartRequest:
    """Canonicalize a replay from persisted defaults, without live discovery."""
    try:
        frozen = read_frozen_team_selection(metadata_json)
        if frozen is None:
            return body
        selection, overrides, fallbacks = normalize_replay_selection(
            frozen=frozen,
            selection=_selection_reference(body.selection),
            overrides={
                role: _selection_reference(reference)
                for role, reference in body.overrides.items()
            },
            fallbacks=tuple(_selection_reference(item) for item in body.fallbacks),
        )
    except (TeamSelectionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return body.model_copy(
        update={
            "selection": _wire_reference(selection),
            "overrides": {
                role: _wire_reference(reference)
                for role, reference in overrides.items()
            },
            "fallbacks": [_wire_reference(reference) for reference in fallbacks],
        }
    )


async def _catalog_records_within_budget(
    app: FastAPI, canonical: str
) -> tuple[ProviderRecord, ...]:
    """Read *canonical*'s catalog records under a bounded wall-clock budget.

    A WARM catalog answers from the per-lane cache immediately, which is the
    normal case: a client cannot produce a valid selection without having read
    the catalog first. The cold case is real anyway - a gateway restart, or the
    workspace scope evicted under capacity, between that read and this start -
    and building cold probes every registered lane over subprocesses and the
    network. A request absorbing that is indistinguishable to the caller from a
    hung gateway.

    Shared by BOTH readers of the catalog - the run start that revalidates a
    selection and the ``provider-catalog`` verb that serves one. The verb is the
    colder of the two by construction: it is the read a client makes precisely
    when it has no selection yet, so it is the caller that most often meets an
    unbuilt workspace. Leaving it on the unbounded service call made a lane that
    wedged hang the verb for as long as the lane took, with no refusal a client
    could act on.

    The build is SHIELDED rather than cancelled on expiry. Cancelling it would
    make every retry pay the same cold cost and never converge; letting it finish
    populates the per-lane single-flight cache, so the caller's retry is warm.
    The refusal is therefore a genuine "not yet", not a failure.
    """
    service = provider_catalog_service(app)
    build = asyncio.ensure_future(service.records(canonical))
    try:
        return await asyncio.wait_for(
            asyncio.shield(build), domain_config.run_start_catalog_budget_seconds
        )
    except TimeoutError:
        # The shielded build outlives this request. Consume its outcome so a
        # later failure is neither an unretrieved-exception warning nor silent.
        build.add_done_callback(_log_detached_catalog_build)
        logger.warning(
            "refused: provider catalog for workspace=%s did not build within "
            "%.1fs; the build continues and a retry will be served warm",
            canonical,
            domain_config.run_start_catalog_budget_seconds,
        )
        raise HTTPException(
            status_code=503,
            detail="the provider catalog for this workspace is still being built",
        ) from None


def _log_detached_catalog_build(task: asyncio.Future[Any]) -> None:
    """Record how a catalog build that outlived its request finished."""
    if task.cancelled():
        logger.warning("detached provider catalog build was cancelled")
        return
    error = task.exception()
    if error is not None:
        logger.warning(
            "detached provider catalog build failed: %s", type(error).__name__
        )


async def _validate_and_freeze_selection_or_refuse(
    app: FastAPI,
    body: RunStartRequest,
    team_config: TeamConfig,
    workspace_root: Path | None,
) -> FrozenTeamSelection:
    """Revalidate the complete new-run selection in its canonical workspace."""
    if workspace_root is None:
        raise HTTPException(
            status_code=422,
            detail="explicit provider selection requires an existing workspace_root",
        )
    canonical = str(require_existing_workspace_root(str(workspace_root)))
    try:
        records = await _catalog_records_within_budget(app, canonical)
    except ProviderCatalogScopeCapacityError:
        # Disclosed for the same reason the admission refusals are: a bare 503
        # here is indistinguishable from an admission or eligibility refusal,
        # and this one is about the catalog's bounded workspace scopes rather
        # than about the run at all.
        logger.warning(
            "run refused: provider catalog workspace scope capacity exhausted "
            "for workspace=%s",
            canonical,
        )
        raise HTTPException(
            status_code=503,
            detail="provider catalog workspace capacity is temporarily busy",
        ) from None
    try:
        return freeze_team_selection(
            selection=_selection_reference(body.selection),
            overrides={
                role: _selection_reference(reference)
                for role, reference in body.overrides.items()
            },
            fallbacks=tuple(_selection_reference(item) for item in body.fallbacks),
            required_roles=tuple(required_role_ids(team_config)),
            records=records,
        )
    except (TeamSelectionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# The metadata key binding a run to its non-secret admission lease identity. The
# gateway writes it at commit and the terminal handler reads it back; both restate
# this key inline, matching the metadata convention used for frozen selection.
_RUN_LEASE_METADATA_KEY = "run_lease"

# The canonical digest of the request that created a run. Persisted on every
# create so a later replay can be compared against what the run was actually
# started with, rather than against the single field the check previously read.
# The stored value is the rule-stamped form (``<rule>:<digest>``).
_REQUEST_DIGEST_METADATA_KEY = "run_request_digest"


def _persist_request_digest(metadata_json: str | None, digest: str) -> str:
    """Embed the creating request's rule-stamped digest into run metadata."""
    data = _metadata_object(metadata_json) or {}
    data[_REQUEST_DIGEST_METADATA_KEY] = digest
    return json.dumps(data)


def _persisted_request_digest(metadata_json: str | None) -> str | None:
    """Read the creating request's rule-stamped digest, or ``None`` when absent.

    Every run records its digest at creation, because a start always carries a
    caller-supplied run id. ``None`` therefore means the metadata cannot be tied
    to any request, never that the request was empty.
    """
    data = _metadata_object(metadata_json)
    digest = data.get(_REQUEST_DIGEST_METADATA_KEY) if data is not None else None
    return digest if isinstance(digest, str) and digest else None


def _replay_identity_or_conflict(
    run_id: str, metadata_json: str | None, body: RunStartRequest
) -> None:
    """Refuse a same-run-id request that is not a replay of the durable run.

    The single encoding of run-start replay identity, applied wherever a request
    meets a run that already owns its id: the sequential check-then-act retry,
    and the loser of a simultaneous insert race. Both arrive at the same
    question - is this the same intention wearing the same id, or a different
    one? - and a second encoding of the answer would be free to drift from the
    first.

    Every behaviour-affecting field - the prompt, the preset, the feature tag,
    the feedback batch, and the canonicalized catalog selection - is folded into
    the persisted replay fingerprint, so a differing request is refused rather
    than silently answered with the durable run and its distinct intention
    discarded.

    Credential VALUES are deliberately not part of that fingerprint. A replay
    returns the ORIGINAL run and never adopts the retry's bundle, and
    short-lived credentials are expected to rotate across a retry, so refusing a
    rotated bundle here would refuse exactly the lost-acknowledgement recovery
    this path exists to serve. Credential coverage remains enforced at first
    start by admission, which is where an uncovering bundle is refused. The
    stored fingerprint is compared under the rule it was written with.

    Raises:
        HTTPException: 409 when the request fingerprint differs, or when the
            run records none to compare against.
    """
    persisted_digest = _persisted_request_digest(metadata_json)
    canonical_body = _canonical_replay_body(metadata_json, body)
    if persisted_digest is None or not replay_digest_matches(
        persisted_digest, canonical_body
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run {run_id!r} was already started with a different request "
                "body; a replay must carry the same request to return the "
                "original run"
            ),
        )


def _persist_lease(metadata_json: str | None, binding: _RunLeaseBinding) -> str:
    """Embed the non-secret lease and exact replay binding into run metadata."""
    data = _metadata_object(metadata_json) or {}
    data[_RUN_LEASE_METADATA_KEY] = {
        "lease_id": binding.lease_id,
        "reservation_id": binding.reservation_id,
        "commit_digest": binding.commit_digest,
    }
    return json.dumps(data)


def _legacy_lease_id(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(RUN_ID_PATTERN, value):
        return value
    return None


def _persisted_lease_id(metadata_json: str | None) -> str | None:
    """Read current or legacy non-secret lease metadata from a durable run."""
    binding = _persisted_lease_binding(metadata_json)
    if binding is not None:
        return binding.lease_id
    data = _metadata_object(metadata_json)
    lease = data.get(_RUN_LEASE_METADATA_KEY) if data is not None else None
    lease_object = coerce_object_mapping(lease)
    if lease_object is None:
        return None
    return _legacy_lease_id(lease_object.get("lease_id"))


def _persisted_lease_binding(metadata_json: str | None) -> _RunLeaseBinding | None:
    """Read the exact staged-commit replay binding from durable metadata."""
    data = _metadata_object(metadata_json)
    if data is None:
        return None
    lease = coerce_object_mapping(data.get(_RUN_LEASE_METADATA_KEY))
    if lease is None:
        return None
    lease_id = _string_field(lease, "lease_id")
    reservation_id = _string_field(lease, "reservation_id")
    commit_digest = _string_field(lease, "commit_digest")
    if not lease_id or not reservation_id or not commit_digest:
        return None
    return _RunLeaseBinding(
        lease_id=lease_id,
        reservation_id=reservation_id,
        commit_digest=commit_digest,
    )


def _load_preset_or_refuse(team_preset: str, ws_root: Path | None) -> TeamConfig:
    """Load the preset with the run's workspace context or refuse with a 422.

    The v1 verb never silently drafts a run for a missing or unparseable preset:
    a load or validation failure is a client error, returned as a 422 with a safe
    reason rather than a non-running draft. Each run-start request loads its
    preset here exactly once; everything downstream reuses that configuration.
    """

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


def _probe_harness(team_config: TeamConfig, ws_root: Path | None) -> Any:
    """Probe the agent harness for a document-authoring preset, else ``None``.

    A non-authoring preset carries no harness requirement, so it returns ``None``
    (composes nothing into eligibility; pre-existing refusals unchanged). A
    document-authoring preset ALWAYS yields a verdict: the verifier's over a
    resolved workspace, or a synthetic not-ready verdict when no workspace is
    resolved - a workspaceless authoring run cannot possibly carry a complete
    harness, so it is refused, not silently skipped (operator override possible,
    silent degradation never). This preserves the
    discovery-serves / run-start-refuses binding uniformly. Read-only.
    """
    from ...context.harness import HarnessReadiness
    from ...providers.provider_readiness import probe_harness_ready

    harness_decl = team_config.effective_harness()
    if harness_decl is None:
        return None
    if ws_root is None:
        return HarnessReadiness(
            ready=False,
            reasons=["no workspace resolved for a document-authoring preset"],
        )
    return probe_harness_ready(
        ws_root, required_skills=harness_decl.all_required_skills()
    )


def _persist_team_selection(
    metadata_json: str | None, frozen: FrozenTeamSelection
) -> str:
    """Persist the normalized schema-v1 catalog selection."""
    data = _metadata_object(metadata_json) or {}
    record_frozen_team_selection(data, frozen)
    return json.dumps(data)


def _modern_frozen_disclosure(
    frozen: FrozenTeamSelection | None,
) -> FrozenTeamAssignmentSummary | None:
    """Project only validated modern selections onto the public frozen shape."""
    if frozen is None:
        return None
    return FrozenTeamAssignmentSummary.model_validate(frozen.disclosure())


# Import after the shared helpers are defined; decorators register on this router.
# isort: off
from ._gateway_run_start import (  # noqa: E402
    _RunLeaseBinding,
)
from . import _gateway_read_endpoints as _read_router_registration  # noqa: E402
from . import _gateway_action_endpoints as _action_router_registration  # noqa: E402

# isort: on
del _read_router_registration, _action_router_registration
