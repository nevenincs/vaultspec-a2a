"""Consolidated health-data assembly for gateway health endpoints.

The single ``/health`` surface serves both liveness and readiness from a common
set of worker, circuit breaker, spawner, and infrastructure diagnostics.
This module provides ``assemble_health_status()`` as the single source of
truth for that shared data, plus ``build_sqlite_fallback_diagnostics()``
which was previously inlined in ``api/app.py``.

``build_full_health()`` is the async service function that runs all probes
(database, worker HTTP, checkpoint, circuit breaker) and returns the
complete readiness payload ``/health`` serves on the unarmed profiles.

``assemble_desktop_readiness()`` is also the single readiness authority used by
:mod:`vaultspec_a2a.control.admission` through
:mod:`vaultspec_a2a.api.routes.gateway`; a prepare refuses admission unless its
worker, provider, and admission facts are execution-ready.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text

from ..database.session import inspect_sqlite_database
from .config import settings
from .worker_management import LazyWorkerSpawner, WorkerState, probe_worker_health

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..api.schemas.gateway import DesktopReadiness
    from .circuit_breaker import WorkerCircuitBreaker

__all__ = [
    "assemble_desktop_readiness",
    "assemble_health_status",
    "build_full_health",
    "build_sqlite_fallback_diagnostics",
    "probe_engine_discovery_freshness",
]

logger = logging.getLogger(__name__)
_OBJECT_MAPPING = TypeAdapter(dict[str, object])


def _object_mapping(value: object) -> Mapping[str, object] | None:
    """Narrow an unstructured app-state value to an object-keyed mapping."""
    try:
        return _OBJECT_MAPPING.validate_python(value)
    except ValidationError:
        return None


def probe_engine_discovery_freshness() -> bool | None:
    """Return engine authoring-backend discovery freshness without an HTTP probe.

    Reads the engine service.json candidates (the env override then the
    machine-global path) and classifies them by heartbeat only - never a live
    ``/health`` call - so the service-state path stays non-blocking. Returns True
    when a fresh, well-formed record is present, False when a record is present
    but stale or malformed, and None when no engine discovery file is configured
    for this process (authoring is simply not wired here).
    """
    import os
    import time
    from pathlib import Path

    from ..authoring.discovery import (
        SERVICE_JSON_ENV,
        heartbeat_is_fresh,
        read_service_json,
    )

    candidates: list[Path] = []
    env_path = os.environ.get(SERVICE_JSON_ENV)
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".vaultspec" / "service.json")

    now_ms = int(time.time() * 1000)
    any_present = False
    for path in candidates:
        info = read_service_json(path)
        if info is None:
            continue
        any_present = True
        if heartbeat_is_fresh(info, now_ms) and isinstance(info.get("port"), int):
            return True
    return False if any_present else None


def build_sqlite_fallback_diagnostics(
    *,
    database_backend: str | None = None,
    checkpoint_backend: str | None = None,
    database_path: Path | None = None,
    checkpoint_path: Path | None = None,
    busy_timeout_ms: int | None = None,
) -> dict[str, object] | None:
    """Build explicit diagnostics for the SQLite fallback path."""
    resolved_database_backend = database_backend or settings.resolved_database_backend
    resolved_checkpoint_backend = (
        checkpoint_backend or settings.resolved_checkpoint_backend
    )
    if (
        resolved_database_backend != "sqlite"
        and resolved_checkpoint_backend != "sqlite"
    ):
        return None

    diagnostics: dict[str, object] = {
        "active": True,
        "busy_timeout_ms": busy_timeout_ms or settings.sqlite_busy_timeout_ms,
        "production_certifying": False,
        "limitations": ["sqlite_fallback_not_production_certifying"],
    }
    if resolved_database_backend == "sqlite":
        diagnostics["database"] = inspect_sqlite_database(
            database_path or settings.database_path
        )
    if resolved_checkpoint_backend == "sqlite":
        diagnostics["checkpoint"] = inspect_sqlite_database(
            checkpoint_path or settings.checkpoint_path
        )
    return diagnostics


def _reported_str(body: Mapping[str, object] | None, key: str) -> str | None:
    """Return a string field a worker reported, or ``None`` when it reported none.

    ``None`` means "the worker did not answer, or carried no such field"; an empty
    string means "the worker answered and reported it blank". The two are kept
    distinct on purpose: blank pairing evidence is the signature of a worker no
    gateway spawned, and collapsing it into ``None`` would erase the difference
    between a silent worker and one that honestly declares it is unpaired.
    """
    if body is None:
        return None
    value = body.get(key)
    return value if isinstance(value, str) else None


def assemble_health_status(
    *,
    app_state: object,
) -> dict[str, object]:
    """Assemble the shared health-status payload from app state.

    Reads circuit breaker, spawner, worker state, repair summary, and SQLite
    fallback diagnostics from ``app_state``.  The returned dict contains all
    fields the readiness aggregate and the desktop projection share; each caller
    adds its own unique fields on top.

    Parameters
    ----------
    app_state:
        The FastAPI ``app.state`` object carrying runtime singletons.

    Returns
    -------
    dict
        Shared health fields ready for inclusion in either endpoint's response.
    """
    from .circuit_breaker import WorkerCircuitBreaker

    # --- Circuit breaker ---
    cb_value: object = getattr(app_state, "circuit_breaker", None)
    cb = cb_value if isinstance(cb_value, WorkerCircuitBreaker) else None
    cb_state = cb.state if cb is not None else "unknown"

    # --- Spawner ---
    spawner_value: object = getattr(app_state, "worker_spawner", None)
    spawner = spawner_value if isinstance(spawner_value, LazyWorkerSpawner) else None
    worker_spawned = spawner.spawned if spawner is not None else False
    worker_pid = (
        spawner.process.pid if spawner is not None and spawner.process else None
    )

    # --- Worker heartbeat ---
    last_hb: object = getattr(app_state, "worker_last_heartbeat_ts", None)
    worker_connected = False
    if (
        not isinstance(last_hb, bool)
        and isinstance(last_hb, (int, float))
        and math.isfinite(last_hb)
    ):
        worker_connected = (
            time.monotonic() - last_hb
        ) < settings.worker_heartbeat_timeout_seconds

    # --- Worker state ---
    worker_state_value: object = getattr(app_state, "worker_state", None)
    ws = worker_state_value if isinstance(worker_state_value, WorkerState) else None
    worker_status = ws.worker_status if ws is not None else "unknown"
    worker_restart_count = ws.worker_restart_count if ws is not None else 0
    worker_last_restart_reason = (
        ws.worker_last_restart_reason if ws is not None else None
    )
    worker_last_restart_detail = (
        ws.worker_last_restart_detail if ws is not None else None
    )
    worker_last_restart_started_at = (
        ws.worker_last_restart_started_at if ws is not None else None
    )
    worker_last_restart_completed_at = (
        ws.worker_last_restart_completed_at if ws is not None else None
    )
    worker_last_restart_succeeded = (
        ws.worker_last_restart_succeeded if ws is not None else None
    )
    worker_last_restart_attempts = (
        ws.worker_last_restart_attempts if ws is not None else 0
    )
    worker_stderr_log_path = ws.worker_stderr_log_path if ws is not None else None

    # --- Repair summary ---
    repair_summary_value: object = getattr(app_state, "repair_summary", None)
    repair_summary = _object_mapping(repair_summary_value)
    if repair_summary is None:
        repair_summary = {
            "repair_backlog": 0,
            "paused_resumable": 0,
            "checkpoint_unavailable": 0,
        }

    # --- SQLite fallback ---
    sqlite_fallback_diagnostics: object = getattr(
        app_state, "sqlite_fallback_diagnostics", None
    )

    # A band gateway dispatching outside the worker-dev band with no band worker
    # present (the non-fatal half of the dispatch-pairing guard) surfaces here so an
    # operator sees the mis-target without reading logs.
    dispatch_pairing_warning: object = getattr(
        app_state, "dispatch_pairing_warning", None
    )

    return {
        "circuit_breaker": cb_state,
        "worker_connected": worker_connected,
        "worker_spawned": worker_spawned,
        "worker_pid": worker_pid,
        "worker_status": worker_status,
        "worker_restart_count": worker_restart_count,
        "worker_last_restart_reason": worker_last_restart_reason,
        "worker_last_restart_detail": worker_last_restart_detail,
        "worker_last_restart_started_at": worker_last_restart_started_at,
        "worker_last_restart_completed_at": worker_last_restart_completed_at,
        "worker_last_restart_succeeded": worker_last_restart_succeeded,
        "worker_last_restart_attempts": worker_last_restart_attempts,
        "worker_stderr_log_path": worker_stderr_log_path,
        "database_backend": settings.resolved_database_backend,
        "checkpoint_backend": settings.resolved_checkpoint_backend,
        "postgres_required": settings.postgres_required,
        "repair_backlog": repair_summary.get("repair_backlog", 0),
        "paused_resumable": repair_summary.get("paused_resumable", 0),
        "checkpoint_unavailable": repair_summary.get("checkpoint_unavailable", 0),
        "sqlite_fallback": sqlite_fallback_diagnostics,
        "dispatch_pairing_warning": dispatch_pairing_warning,
    }


def _eligible_provider_names() -> list[str]:
    """Return the subprocess providers that can actually run on this host.

    Uses ``probe_provider_readiness`` - the credential-aware seam that gates on
    the configured credential FIRST and only then on command resolvability. It
    remains no-instantiation: no model is constructed and no subprocess is
    spawned. Resolving the launch command alone is not sufficient, because a
    provider whose binary is installed with its credential absent cannot run;
    admitting it here reserves execution capacity for a run that the
    credential-aware gate applied at launch then refuses.

    Codex is the one provider the resolver deliberately gates on command
    resolvability alone - its auth is a file-based persisted session in the
    Codex home rather than a configured secret, so there is no credential to
    check. That asymmetry is the resolver's to own; this seam does not restate
    it, so the two can never disagree. Z.ai is omitted because it launches the
    same ACP wrapper as Claude; counting it again would double-count one
    backend.
    """
    from ..graph.enums import Provider
    from ..providers.model_profiles import probe_provider_readiness

    candidates = (Provider.CLAUDE, Provider.GEMINI, Provider.CODEX, Provider.KIMI)
    return [
        provider.value
        for provider in candidates
        if probe_provider_readiness(provider).ready
    ]


def assemble_desktop_readiness(
    *,
    app_state: object,
    database_ready: bool | None = None,
    worker_probe_ready: bool | None = None,
) -> DesktopReadiness:
    """Assemble the five separate desktop readiness facts from one authority.

    This is the single place readiness is computed: the unauthenticated liveness
    surface and the service-state verb both call it, so gateway readiness, worker
    state, provider eligibility, and run admission can never drift between the two.

    Gateway readiness turns only on a valid database - a live gateway with a valid
    database is ready even while its worker is cold, because worker absence before
    demand is informational, not degradation. Callers that have already run the
    live database and worker probes pass their verdicts in (``database_ready``,
    ``worker_probe_ready``); the cheap sync surface leaves them ``None`` and the
    fact is derived from seated application state. Run admission is the distinct
    execution-readiness fact: a reachable worker plus an eligible provider is
    ``ready``; a cold or starting worker over a ready gateway is ``deferred``; a
    failed hard dependency is ``blocked``.
    """
    import os

    from ..api.schemas.gateway import (
        DesktopReadiness,
        GatewayReadiness,
        LivenessState,
        ProviderEligibility,
        RunAdmission,
        WorkerLifecycleState,
    )
    from ..utils import package_version

    shared = assemble_health_status(app_state=app_state)
    reasons: list[str] = []

    # --- Gateway readiness: a valid database, worker state notwithstanding. ---
    # Under the armed desktop profile the schema is validated at boot and the
    # gateway fails closed otherwise, so a seated engine is a valid database. A
    # caller that already ran the live probe passes its verdict in instead.
    if database_ready is None:
        database_valid = getattr(app_state, "db_engine", None) is not None
    else:
        database_valid = database_ready
    if database_valid:
        gateway_readiness = GatewayReadiness.READY
    else:
        gateway_readiness = GatewayReadiness.NOT_READY
        reasons.append("database is not valid")

    # --- Worker lifecycle: the cold-to-execution ladder. ---
    worker_spawned = bool(shared["worker_spawned"])
    worker_status = shared["worker_status"]
    if not worker_spawned:
        # No worker exists yet; one starts on first execution demand.
        worker_state = WorkerLifecycleState.COLD
        reasons.append("worker is cold; starts on first execution demand")
    elif worker_status == "pending":
        # A demand-side caller can complete the worker's real HTTP probe before
        # the watchdog has advanced its cached lifecycle label.  In that narrow
        # window the live probe is the stronger fact: refusing admission as
        # ``starting`` after an exact authenticated 200 would make first demand
        # fail even though ``ensure_worker`` has already completed successfully.
        worker_state = (
            WorkerLifecycleState.READY
            if worker_probe_ready is True
            else WorkerLifecycleState.STARTING
        )
    elif worker_status in {"down", "restarting"}:
        worker_state = WorkerLifecycleState.UNAVAILABLE
        reasons.append(f"worker is {worker_status}")
    else:
        worker_reachable = (
            worker_probe_ready
            if worker_probe_ready is not None
            else bool(shared["worker_connected"])
        )
        worker_state = (
            WorkerLifecycleState.READY
            if worker_reachable
            else WorkerLifecycleState.STARTING
        )

    # --- Provider eligibility via the credential-aware readiness probe. ---
    eligible_providers = _eligible_provider_names()
    if eligible_providers:
        provider_eligibility = ProviderEligibility.ELIGIBLE
    else:
        provider_eligibility = ProviderEligibility.INELIGIBLE
        reasons.append("no subprocess provider is installed and credentialed here")

    # --- Run admission: execution readiness, distinct from gateway readiness. ---
    if gateway_readiness is not GatewayReadiness.READY:
        run_admission = RunAdmission.BLOCKED
    elif (
        worker_state is WorkerLifecycleState.READY
        and provider_eligibility is ProviderEligibility.ELIGIBLE
    ):
        run_admission = RunAdmission.READY
    else:
        run_admission = RunAdmission.DEFERRED

    return DesktopReadiness(
        gateway_pid=os.getpid(),
        generation=package_version(),
        profile="desktop" if settings.desktop_profile_armed else "compose",
        liveness=LivenessState.ALIVE,
        gateway_readiness=gateway_readiness,
        worker_state=worker_state,
        provider_eligibility=provider_eligibility,
        eligible_providers=eligible_providers,
        run_admission=run_admission,
        reasons=reasons[:16],
    )


async def build_full_health(
    *,
    db: AsyncSession,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    app_state: object,
    include_pairing: bool = False,
) -> dict[str, object]:
    """Run all health probes and return the complete readiness payload.

    This is the service-layer orchestration ``/health`` serves unarmed.
    It runs the DB probe, worker HTTP check, checkpoint presence test,
    circuit breaker and spawner inspection, then computes overall readiness.

    *include_pairing* adds what the worker reported about which gateway
    incarnation spawned it. It is opt-in and defaults off because this payload
    is served verbatim on the UNAUTHENTICATED health endpoint under the Compose
    and development profiles, and the gateway's lifetime identity is exactly the
    value a port squatter must not be able to learn: the armed adoption check
    trusts it precisely because it is unguessable. Only the attach-authenticated
    readiness surface asks for it.
    """
    shared = assemble_health_status(app_state=app_state)

    checks: dict[str, dict[str, str]] = {}
    checks["gateway"] = {"status": "ok"}

    # --- Database probe ---
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            "backend": settings.resolved_database_backend,
            "postgres_required": "yes" if settings.postgres_required else "no",
        }
    except Exception:
        logger.exception("Health check: database probe failed")
        checks["database"] = {
            "status": "error",
            "backend": settings.resolved_database_backend,
            "detail": "database probe failed",
            "postgres_required": "yes" if settings.postgres_required else "no",
        }

    # --- Checkpointer probe ---
    checkpointer = getattr(app_state, "checkpointer", None)
    checkpoint_check: dict[str, str] = {
        "backend": settings.resolved_checkpoint_backend,
        "postgres_required": "yes" if settings.postgres_required else "no",
    }
    if checkpointer is None:
        checkpoint_check["status"] = "error"
        checkpoint_check["detail"] = "checkpointer missing"
    else:
        try:
            await asyncio.wait_for(
                checkpointer.aget_tuple(
                    {
                        "configurable": {
                            "thread_id": "__health_probe__",
                            "checkpoint_ns": "",
                        }
                    }
                ),
                timeout=5.0,
            )
            checkpoint_check["status"] = "ok"
        except TimeoutError:
            logger.warning("Health check: checkpoint probe timed out")
            checkpoint_check["status"] = "error"
            checkpoint_check["detail"] = "checkpoint probe timed out"
        except Exception:
            logger.exception("Health check: checkpoint probe failed")
            checkpoint_check["status"] = "error"
            checkpoint_check["detail"] = "checkpoint probe failed"
    checks["checkpoint"] = checkpoint_check

    # --- Worker HTTP probe ---
    # The single worker-health primitive, reusing the pooled client; "healthy" is an
    # exact 200 for both this endpoint and the watchdog, so they cannot disagree.
    # The same round trip hands back what the worker REPORTED about its pairing, so
    # the readiness surface echoes that evidence without a second probe.
    worker_probe = await probe_worker_health(
        settings.worker_url, timeout=5.0, client=worker_client
    )
    if worker_probe.healthy:
        checks["worker"] = {"status": "ok"}
    else:
        logger.warning("Health check: worker probe failed")
        checks["worker"] = {"status": "error", "detail": "worker probe failed"}

    # Echoed, never asserted: which gateway incarnation the worker says spawned it
    # and which spawn attempt it was. Absent when the worker did not answer or did
    # not report them - a worker no gateway spawned reports them blank, which is
    # the honest answer and must not be dressed up as this gateway's own identity.
    pairing: dict[str, object] = {}
    if include_pairing:
        pairing = {
            "worker_paired_gateway_lifetime": _reported_str(
                worker_probe.body, "paired_gateway_lifetime"
            ),
            "worker_reported_generation": _reported_str(
                worker_probe.body, "worker_generation"
            ),
        }

    # --- Circuit breaker & spawner ---
    checks["circuit_breaker"] = {"status": circuit_breaker.state}
    checks["worker_spawned"] = {"status": "yes" if worker_spawner.spawned else "no"}
    if shared["worker_stderr_log_path"] is not None:
        checks["worker_stderr_log"] = {"status": "configured"}

    # --- Overall readiness ---
    ready = (
        checks["gateway"]["status"] == "ok"
        and checks["database"]["status"] == "ok"
        and checks["checkpoint"]["status"] == "ok"
        and checks["worker"]["status"] == "ok"
        and checks["circuit_breaker"]["status"] == "closed"
    )
    return {
        "status": "ok" if ready else "degraded",
        "checks": checks,
        **pairing,
        **shared,
    }
