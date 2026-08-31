"""Worker process management — lazy spawner, watchdog, and helpers.

Infrastructure for managing the worker subprocess lifecycle.  Protocol-
agnostic: no FastAPI/HTTP imports.  The caller (``api/app.py``) is responsible
for storing ``WorkerState`` on ``app.state`` and wiring it to route handlers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import httpx

    from .circuit_breaker import WorkerCircuitBreaker

from ..artifacts import ArtifactDeclaration, RetentionDisposition
from ..lifecycle.pairing import (
    WorkerPairingVerdict,
    classify_worker_pairing,
    eviction_is_authorized,
)
from ..utils import kill_pid_tree_async
from ..utils.process import ProcessContainment, ProcessContainmentError
from ..utils.runtime_exec import module_command
from .config import GATEWAY_URL_ENV, INTERNAL_TOKEN_ENV, settings
from .worker_status import WorkerConnectionStatus

__all__ = [
    "LazyWorkerSpawner",
    "WorkerHealthProbe",
    "WorkerLiveness",
    "WorkerState",
    "WorkerWatchdog",
    "probe_worker_health",
    "sweep_orphan_worker_logs",
    "worker_liveness",
    "worker_ready_and_ours",
]

logger = logging.getLogger(__name__)

_WORKER_STDERR_TAIL_BYTES = 4096
_JSON_OBJECT = TypeAdapter(dict[str, object])


# ---------------------------------------------------------------------------
# WorkerState dataclass — decouples watchdog from app.state
# ---------------------------------------------------------------------------


@dataclass
class WorkerState:
    """Mutable container for worker lifecycle metadata.

    The watchdog writes to this dataclass instead of directly onto
    ``app.state``.  The lifespan creates it, passes it to the watchdog,
    and also stores it on ``app.state`` for route handlers to read.

    Attributes match the 9 fields the watchdog previously wrote directly
    onto ``app.state``.
    """

    worker_status: str = WorkerConnectionStatus.PENDING.value
    worker_restart_count: int = 0
    worker_last_restart_reason: str | None = None
    worker_last_restart_detail: str | None = None
    worker_last_restart_started_at: str | None = None
    worker_last_restart_completed_at: str | None = None
    worker_last_restart_succeeded: bool | None = None
    worker_last_restart_attempts: int = 0
    worker_stderr_log_path: str | None = None


@dataclass
class WorkerLiveness:
    """When the gateway last heard from its worker, and what it was running.

    Sited beside the timeout rule that gives the value meaning, because the rule
    is the only thing that makes a monotonic float mean "connected" or "stale".
    Both readings are declared here as :meth:`is_fresh` and :meth:`is_stale`, and
    they are deliberately not complements: at exactly the timeout neither holds,
    and a worker never heard from is not stale, it has simply not started.

    Recording contact and interpreting it used to sit apart. The stamp was an
    undeclared attribute assigned inline at five sites, so neither reader could
    assume it existed and both read it through a defaulted ``getattr`` with their
    own copy of the validity guard. That defensiveness was not protection: an
    absent stamp and a stamp nobody had written yet arrive identically, and both
    surface as "worker unreachable" — the one failure the value exists to rule
    out. A writer that must be reached through this type cannot forget it, and a
    reader can now ask a question instead of guessing at a field.
    """

    last_contact_ts: float | None = None
    active_threads: list[str] = field(default_factory=list)

    def record_contact(
        self,
        *,
        when: float | None = None,
        active_threads: Sequence[str] | None = None,
    ) -> None:
        """Record that the worker was heard from.

        *when* is a :func:`time.monotonic` reading, defaulting to now; a caller
        supplies one only when contact happened measurably before it could say
        so. *active_threads* is omitted by a caller that observed contact without
        learning what the worker is running (a socket accept, a dispatch
        acknowledgement) — omission leaves the last known set standing rather
        than blanking it, which an empty list would.
        """
        self.last_contact_ts = time.monotonic() if when is None else when
        if active_threads is not None:
            self.active_threads = list(active_threads)

    def age_seconds(self, *, now: float | None = None) -> float | None:
        """Seconds since the last recorded contact, or ``None`` if never heard from.

        A stamp that is not a finite real number reads as no contact at all. The
        guard survives the move because ``app.state`` stays an untyped attribute
        bag that an embedding host can seat anything on, and because both
        predicates below must agree about a degenerate value rather than one
        reading it as fresh and the other as stale.
        """
        stamp: object = self.last_contact_ts
        if (
            isinstance(stamp, bool)
            or not isinstance(stamp, (int, float))
            or not math.isfinite(stamp)
        ):
            return None
        return (time.monotonic() if now is None else now) - stamp

    def is_fresh(self, *, now: float | None = None) -> bool:
        """Whether contact is recent enough to report the worker as connected."""
        age = self.age_seconds(now=now)
        return age is not None and age < settings.worker_heartbeat_timeout_seconds

    def is_stale(self, *, now: float | None = None) -> bool:
        """Whether contact was made and has since aged past the heartbeat timeout.

        A worker never heard from is NOT stale. Reporting it as such would hand
        the watchdog a crash signal for a worker that has not finished starting.
        """
        age = self.age_seconds(now=now)
        return age is not None and age > settings.worker_heartbeat_timeout_seconds


def worker_liveness(app_state: Any) -> WorkerLiveness:
    """Return the liveness record on *app_state*, seating one when it has none.

    The single accessor every writer and reader goes through. Seating on demand
    keeps a host that embeds the internal router without the gateway lifespan
    working, and costs nothing in meaning: a fresh record says the worker has
    never been heard from, which is exactly what an app carrying no record knows.
    """
    existing = getattr(app_state, "worker_liveness", None)
    if isinstance(existing, WorkerLiveness):
        return existing
    seated = WorkerLiveness()
    app_state.worker_liveness = seated
    return seated


@dataclass(frozen=True, slots=True)
class WorkerHealthProbe:
    """One authenticated worker health observation.

    ``healthy`` is determined solely by an exact HTTP 200.  ``body`` is an
    optional decoded object: it carries pairing evidence when readable, while
    ``None`` deliberately distinguishes unreadable evidence from a healthy
    occupant's absence only through ``healthy``.

    ``indeterminate`` separates the two ways ``healthy`` can be False. A refused
    connection PROVES no worker holds the port. A read that outran its budget
    proves only that this observation did not finish in time - a worker busy
    compiling a graph for an already-admitted run is unresponsive for seconds and
    then answers normally. Callers that must not act on absence they did not
    observe (run admission) read this and fall back to the watchdog's seated
    state; callers that restart on a hung worker keep reading ``healthy`` alone.
    """

    healthy: bool
    body: Mapping[str, object] | None
    indeterminate: bool = False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _runtime_dir() -> Path:
    """Return the machine-global runtime directory for gateway-managed process logs.

    Lives under the A2A home, not inside ``.vault/`` — vaultspec
    firmware rejects foreign directories inside the vault.
    """
    runtime_dir = settings.a2a_home / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _worker_stderr_log_path(worker_port: int) -> Path:
    """Return the deterministic stderr log path for the auto-spawned worker."""
    return _runtime_dir() / f"worker-autospawn-{worker_port}.stderr.log"


GATEWAY_LIFETIME_ENV = "VAULTSPEC_GATEWAY_LIFETIME_ID"
"""Env name carrying the spawning gateway's lifetime identity to its worker."""

WORKER_GENERATION_ENV = "VAULTSPEC_WORKER_GENERATION"
"""Env name carrying the spawn generation this worker belongs to."""

# One value per gateway PROCESS, not per port or per host. A gateway that
# restarts on the same port is a different incarnation, and a worker still
# holding the previous value is paired to a gateway that no longer exists -
# the condition a URL comparison cannot see, and the one that let dispatch
# reach a foreign worker.
GATEWAY_LIFETIME_ID = uuid.uuid4().hex


_WORKER_LOG_NAME_RE = re.compile(r"^worker-autospawn-(\d+)\.stderr\.log$")

# The port-keyed filename is why this artifact accumulated: a dev-band worker
# takes a fresh port each boot, so every boot minted a new file and nothing
# reclaimed the previous one. The sweep below is the enforcement, and it runs
# once per gateway boot rather than continuously, so orphans from a boot that
# never recurs are only reclaimed when some later gateway starts.
WORKER_STDERR_LOG_DECLARATION = ArtifactDeclaration(
    name="worker-autospawn-stderr-log",
    root="<a2a_home>/runtime/worker-autospawn-<port>.stderr.log",
    owner="control.worker_management",
    disposition=RetentionDisposition.SESSION_SCOPED,
    mechanism=(
        "truncated on each spawn, and orphans for ports with no live registry "
        "claim are deleted by sweep_orphan_worker_logs once per gateway boot"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (
    WORKER_STDERR_LOG_DECLARATION,
)


def sweep_orphan_worker_logs(
    *, current_worker_port: int, registry_home: Path | None = None
) -> list[Path]:
    """Delete ``worker-autospawn-<port>.stderr.log`` files with no live claim.

    A dev-band worker instance gets a fresh port (hence a fresh log filename)
    every boot, so the runtime dir accumulates one orphaned file per past
    instance forever - no reap ever touched them (research: 15+ accumulated at
    audit time). Meant to run once per gateway boot, before this process spawns
    its own worker: a file's port is kept when it is the port THIS process is
    about to (re)use, or when the dev-process registry (``~/.vaultspec/procs``,
    a separate registry from this gateway's own service discovery) still shows
    a live record on that port; every other file is a stale orphan and removed.
    Best-effort per file and per registry read - neither may abort a real boot.
    """
    from ..lifecycle.registry import StalenessState, classify_record, list_records

    try:
        live_ports: set[int] = {
            record.port
            for record in list_records(registry_home)
            if classify_record(record, None) is StalenessState.LIVE
        }
    except OSError:
        live_ports = set()

    removed: list[Path] = []
    for path in _runtime_dir().glob("worker-autospawn-*.stderr.log"):
        match = _WORKER_LOG_NAME_RE.match(path.name)
        if match is None:
            continue
        port = int(match.group(1))
        if port == current_worker_port or port in live_ports:
            continue
        with contextlib.suppress(OSError):
            path.unlink()
            removed.append(path)
    return removed


# A UTF-8 continuation byte matches 0b10xxxxxx, a pattern no character ever
# starts with, and a character spans at most four bytes - so at most three
# continuation bytes can sit between an arbitrary offset and the next boundary.
_UTF8_CONTINUATION_MASK = 0xC0
_UTF8_CONTINUATION_MARKER = 0x80
_UTF8_MAX_CONTINUATION_BYTES = 3


def _advance_to_character_boundary(raw: bytes) -> bytes:
    """Drop the partial character a byte-offset seek may have landed inside."""
    index = 0
    while (
        index < min(len(raw), _UTF8_MAX_CONTINUATION_BYTES)
        and raw[index] & _UTF8_CONTINUATION_MASK == _UTF8_CONTINUATION_MARKER
    ):
        index += 1
    return raw[index:]


def _read_log_tail(log_path: Path, max_bytes: int = _WORKER_STDERR_TAIL_BYTES) -> str:
    """Read and decode the tail of a worker stderr log file.

    The tail starts at a byte offset, which for a log carrying non-ASCII provider
    output lands inside a character as often as not. Trimming the stranded
    continuation bytes costs at most three bytes of an already-truncated
    diagnostic and keeps the first line readable, where decoding them would open
    every non-ASCII tail with replacement characters.
    """
    if max_bytes <= 0 or not log_path.exists():
        return ""
    with log_path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        offset = max(size - max_bytes, 0)
        handle.seek(offset)
        raw = handle.read(max_bytes)
    if offset:
        raw = _advance_to_character_boundary(raw)
    return raw.decode("utf-8", errors="replace").strip()


def _build_worker_restart_detail(
    *,
    returncode: int | None,
    stderr_log_path: Path | None,
) -> str:
    """Build a compact diagnostic string for health/readiness surfaces."""
    detail = f"returncode={returncode}"
    stderr_tail = _read_log_tail(stderr_log_path) if stderr_log_path is not None else ""
    if stderr_tail:
        compact_tail = re.sub(r"\s+", " ", stderr_tail)[:500]
        detail += f"; stderr_tail={compact_tail}"
    detail += f"; stderr_log={stderr_log_path}"
    return detail


async def _tcp_port_ready(host: str, port: int) -> bool:
    """Fast-path: check if a TCP port is accepting connections.

    Much cheaper than a full HTTP health check — used to skip expensive
    httpx probes while the process is still binding.
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=0.5,
        )
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError):
        return False
    return True


def _internal_auth_headers() -> dict[str, str] | None:
    """Return the worker-IPC bearer header when the internal token is configured.

    The gateway-worker pair authenticates every probe and command with the shared
    worker interprocess-communication credential; a DEVELOPMENT gateway with no
    token sends none, matching the bearer rule the worker enforces.
    """
    if settings.internal_token is None:
        return None
    return {"Authorization": f"Bearer {settings.internal_token}"}


async def probe_worker_health(
    url: str,
    timeout: float = 2.0,
    *,
    client: httpx.AsyncClient | None = None,
) -> WorkerHealthProbe:
    """Probe the worker's ``GET /health`` once.

    The single worker-health primitive for every caller - the boot/spawn paths,
    the watchdog's authoritative crash check, and ``/health``. Request-path
    callers pass the app-pooled *client* to reuse its connection pool (already
    carrying the worker IPC bearer); the watchdog and boot paths pass none and get
    a self-contained one-shot client that presents the same bearer, so a worker
    that enforces the credential on ``/health`` still answers its owner.

    The health verdict is an exact ``200`` and nothing else, so every caller
    agrees and ``/health`` can never silently diverge from the watchdog's
    restart decision (a ``204`` fails both, not one). The decoded body is a
    strictly additive by-product for callers that also want what the worker
    *reported*: a body that will not decode leaves the verdict untouched and
    yields ``None``, so reporting can never turn a healthy worker unhealthy.
    """
    import httpx

    async def _probe(active: httpx.AsyncClient) -> WorkerHealthProbe:
        resp = await active.get(f"{url}/health", timeout=timeout)
        if resp.status_code != 200:
            return WorkerHealthProbe(healthy=False, body=None)
        try:
            decoded: object = resp.json()
        except ValueError:
            return WorkerHealthProbe(healthy=True, body=None)
        try:
            body = _JSON_OBJECT.validate_python(decoded)
        except ValidationError:
            return WorkerHealthProbe(healthy=True, body=None)
        return WorkerHealthProbe(healthy=True, body=body)

    try:
        if client is not None:
            return await _probe(client)
        async with httpx.AsyncClient(headers=_internal_auth_headers()) as owned:
            return await _probe(owned)
    except Exception as exc:
        # An unreachable verdict decides run admission, so a silent swallow here
        # makes an operator-visible 503 unexplainable: a refused worker, a timed
        # out one, and a crashed one all present identically. Name the cause.
        indeterminate = _is_indeterminate_probe_failure(exc)
        logger.info(
            "Worker health probe failed for %s: %s: %s (indeterminate=%s)",
            url,
            type(exc).__name__,
            exc,
            indeterminate,
        )
        return WorkerHealthProbe(healthy=False, body=None, indeterminate=indeterminate)


def _is_indeterminate_probe_failure(exc: BaseException) -> bool:
    """Whether *exc* leaves the worker's health genuinely unknown.

    A connect failure is decisive evidence of absence: the transport reached the
    port and nothing accepted. Every other transport failure - a read that outran
    its budget, an exhausted client pool, a connection dropped mid-response - says
    something about THIS observation, not about whether a worker exists. Timeouts
    are classified before connect errors because ``ConnectTimeout`` is both, and
    a connect that timed out is an absence observation, not an unknown one.
    """
    import httpx

    if isinstance(exc, httpx.ConnectTimeout | httpx.ConnectError):
        return False
    return isinstance(exc, httpx.TransportError)


def _same_gateway(worker_target: object, our_gateway: str) -> bool:
    """Whether a worker's declared heartbeat target is *this* gateway.

    A missing/blank target (an older worker whose ``/health`` predates the
    ``gateway_url`` field) is treated as a match so the fix never regresses a
    correctly-wired legacy worker into a needless eviction; only a present,
    differing target marks a stale orphan.
    """
    if not isinstance(worker_target, str) or not worker_target:
        return True
    return worker_target.rstrip("/") == our_gateway.rstrip("/")


def _classify_worker_body(
    body: Mapping[str, object], *, current_generation: int
) -> WorkerPairingVerdict:
    """Classify a fetched worker health body against this gateway's identity.

    The single enforcement seam for the authenticated pairing policy: the
    worker's reported ``paired_gateway_lifetime`` and ``worker_generation`` are
    judged by :func:`~vaultspec_a2a.lifecycle.pairing.classify_worker_pairing`
    against THIS process's lifetime identity and the spawner's current
    generation. Blank or foreign evidence fails closed.
    """
    lifetime = body.get("paired_gateway_lifetime")
    generation = body.get("worker_generation")
    return classify_worker_pairing(
        reported_lifetime=lifetime if isinstance(lifetime, str) else None,
        reported_generation=generation if isinstance(generation, str) else None,
        gateway_lifetime=GATEWAY_LIFETIME_ID,
        current_generation=current_generation,
    )


async def worker_ready_and_ours(
    worker_url: str, *, current_generation: int = 0
) -> bool:
    """Whether a healthy worker at *worker_url* is provably THIS gateway's.

    The provenance-aware readiness signal for every adoption decision: a bare
    ``/health`` 200 only proves *some* worker holds the port, which a foreign
    orphan squatting a shared band port satisfies just as well as our own.

    Profile-split enforcement (the authenticated-pairing decision): under the
    ARMED desktop profile the authenticated pairing verdict is the authority -
    only a worker whose reported gateway lifetime and spawn generation classify
    as ``OWNED`` is adopted; blank, legacy, or foreign evidence fails closed.
    Unarmed profiles keep the legacy declared-``gateway_url`` comparison so
    registry- and Compose-managed workers (which legitimately carry no pairing
    evidence) are not disowned.

    An occupant that answered but reported nothing readable is not ours under
    either profile. This is the opposite reading from the spawn path, which
    treats the same occupant as a reason NOT to spawn - deliberately so: "some
    process holds this port" and "this process is provably mine" are different
    questions, and the safe answer to the first is the unsafe answer to the
    second. Only the legacy comparison could get this wrong, since a missing
    declared target reads as a match by design; an empty body is the absence of
    evidence rather than a legacy worker's silence, so it is refused before the
    lenient rule can adopt it.
    """
    probe = await probe_worker_health(worker_url)
    body = probe.body
    if not probe.healthy or body is None:
        return False
    if settings.desktop_profile_armed:
        verdict = _classify_worker_body(body, current_generation=current_generation)
        if verdict is not WorkerPairingVerdict.OWNED:
            logger.warning(
                "Worker at %s is not adoptable under the armed profile "
                "(pairing verdict: %s)",
                worker_url,
                verdict.value,
            )
            return False
        return True
    return _same_gateway(body.get("gateway_url"), settings.gateway_url)


async def _evict_stale_worker(
    worker_url: str,
    worker_port: int,
    *,
    timeout: float = 10.0,
) -> bool:
    """Terminate a stale worker and wait for the port to free.

    Posts the worker's bearer-authenticated ``/admin/shutdown`` (an
    ``os.kill(SIGTERM)`` that is an immediate ``TerminateProcess`` on Windows, not
    a graceful run-draining stop) and polls the TCP port until it stops accepting
    connections. Only ever aimed at a foreign-gateway orphan, never at a worker
    serving this gateway's runs, so the abrupt stop cannot drop live work of ours.
    Returns ``True`` once the port is free, ``False`` if it is still bound after
    *timeout* seconds. The internal token is presented so the shutdown is accepted
    only when this gateway is the worker's paired owner.
    """
    import httpx

    with contextlib.suppress(Exception):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{worker_url}/admin/shutdown",
                headers=_internal_auth_headers(),
                timeout=2.0,
            )

    deadline = asyncio.get_event_loop().time() + timeout
    freed = False
    while asyncio.get_event_loop().time() < deadline:
        if not await _tcp_port_ready("127.0.0.1", worker_port):
            freed = True
            break
        await asyncio.sleep(0.25)
    else:
        freed = not await _tcp_port_ready("127.0.0.1", worker_port)
    if freed:
        # The evicted worker's own stderr log is a dead end from this point:
        # nothing will append to it unless OUR spawn reuses the same port (which
        # truncates it anyway), and an eviction whose follow-up spawn then fails
        # would otherwise leave it behind exactly like the registry orphans this
        # step's kill/reap deletion closes.
        with contextlib.suppress(OSError):
            _worker_stderr_log_path(worker_port).unlink(missing_ok=True)
    return freed


async def _spawn_worker(
    worker_url: str,
    worker_port: int,
    *,
    containment: ProcessContainment | None = None,
    generation: int = 0,
) -> subprocess.Popen[bytes] | None:
    """Spawn the worker as a child process if not already running.

    Returns the ``Process`` handle on success, or ``None`` if the worker was
    already running or failed to become ready within
    ``settings.worker_ready_timeout_seconds``. A worker that spawned but never
    became ready is reaped tree-and-all before returning, so a failed spawn
    never leaves an orphan holding the worker port.

    When *containment* is supplied (the armed desktop gateway owning its worker),
    the worker is spawned inside it - a new POSIX session/process group or a
    Windows Job Object - and assigned before it does any descendant work, so the
    whole worker tree is reaped as one on shutdown. A Windows assignment failure
    is logged and downgraded to the per-pid fallback rather than failing the spawn.

    Ownership contract - the caller allocates *containment* and the caller
    releases it. This function never releases it on the caller's behalf, on any
    exit, so there is no exit the caller has to know about: it releases on every
    return that is not a live process, and on a raise. Splitting that duty (some
    exits releasing here, others expecting the caller to) is what previously let
    three exits leak the handle, so it is stated as one rule rather than a list.

    What this function does guarantee is that nothing it spawned outlives a spawn
    it did not report as successful: any process started here is reaped, tree and
    all, before a ``None`` return or a propagating exception leaves the frame.
    Reaping through a containment closes the handle as a side effect, which is
    harmless - :meth:`ProcessContainment.close` is idempotent - but it is the
    caller's release, not that side effect, that makes the release total.

    Use :func:`_spawn_worker_owned` rather than calling this directly; it is the
    single seam that honours the contract for both spawn paths.
    """
    # The armed desktop gateway owns its worker exclusively, but its private
    # worker port can still be occupied - a surviving prior generation after a
    # containment downgrade, or a stranger process. The authenticated pairing
    # verdict rules on ONE health read (adoption and eviction must share one
    # classification): an OWNED current-generation worker is adopted, a
    # PRIOR_GENERATION worker this gateway demonstrably spawned is evicted
    # under the classifier's authorization (a failed eviction is a conflict,
    # never an adoption), and a FOREIGN or UNIDENTIFIED occupant refuses the
    # spawn loudly with no eviction - it may be serving someone else's runs,
    # and silence is not evidence of ownership.
    if settings.desktop_profile_armed:
        occupant = await probe_worker_health(worker_url)
        if occupant.healthy:
            verdict = _classify_worker_body(
                occupant.body or {}, current_generation=generation
            )
            if verdict is WorkerPairingVerdict.OWNED:
                logger.info(
                    "Worker already running at %s with an owned pairing "
                    "verdict — adopting instead of spawning",
                    worker_url,
                )
                return None
            if eviction_is_authorized(
                verdict, desktop_profile_armed=settings.desktop_profile_armed
            ):
                logger.warning(
                    "Worker at %s is this gateway's prior generation "
                    "(verdict: %s) — evicting before spawning the replacement",
                    worker_url,
                    verdict.value,
                )
                if not await _evict_stale_worker(worker_url, worker_port):
                    logger.error(
                        "Prior-generation worker at %s did not release port %d "
                        "after an authorized eviction — refusing to spawn onto "
                        "a held port (conflict, no adoption)",
                        worker_url,
                        worker_port,
                    )
                    return None
            else:
                logger.error(
                    "Worker port %d is held by a process this gateway cannot "
                    "adopt or evict (pairing verdict: %s) — refusing to spawn "
                    "(conflict, no adoption, no eviction)",
                    worker_port,
                    verdict.value,
                )
                return None
    # Only the Compose and development band profiles probe the port for an
    # already-running same-gateway worker (adopt) or a stale foreign orphan
    # (evict) before spawning, using the legacy declared-gateway_url signal.
    if not settings.desktop_profile_armed:
        existing = await probe_worker_health(worker_url)
        if existing.healthy:
            if existing.body is None:
                logger.error(
                    "Worker port %d is held by a healthy worker with unreadable "
                    "pairing evidence — refusing to spawn or adopt",
                    worker_port,
                )
                return None
            if _same_gateway(
                existing.body.get("gateway_url"),
                settings.gateway_url,
            ):
                logger.info(
                    "Worker already running at %s targeting this gateway (%s)"
                    " — skipping auto-spawn",
                    worker_url,
                    settings.gateway_url,
                )
                return None
            # A stale orphan from a dead dev-band gateway is squatting the worker
            # port: it heartbeats a gateway that no longer exists and would never
            # be re-pointed. Evict it and spawn a fresh worker wired to THIS
            # gateway.
            logger.warning(
                "Worker at %s targets a foreign gateway (%s != %s) — evicting the"
                " stale orphan before spawning a fresh worker",
                worker_url,
                existing.body.get("gateway_url"),
                settings.gateway_url,
            )
            if not await _evict_stale_worker(worker_url, worker_port):
                # The foreign orphan would not release the port. Spawning anyway is
                # the adoption hazard this guard exists to close: our new worker
                # cannot bind the held port, and the readiness probe would find the
                # SURVIVING foreign worker healthy and hand it back as ours. Fail
                # loud instead of spawning a competitor onto a port a foreign
                # gateway's worker still serves.
                logger.error(
                    "Stale worker at %s did not release port %d after eviction —"
                    " refusing to spawn onto a foreign-held port (manual reap"
                    " required)",
                    worker_url,
                    worker_port,
                )
                return None

    logger.info(
        "Auto-spawning worker on port %d",
        worker_port,
    )
    logger.info(
        "Worker spawn env snapshot: gateway_port=%s worker_port=%s"
        " worker_url=%s gateway_url=%s",
        settings.port,
        settings.worker_port,
        settings.worker_url,
        settings.gateway_url,
    )

    # Explicitly propagate critical config to the worker subprocess.
    # While Python's subprocess.Popen() inherits the parent env by default,
    # the gateway may have auto-derived gateway_url from host+port.  That
    # computed value is NOT in os.environ, so the child would re-derive it
    # and potentially get a different result (e.g. 0.0.0.0 vs 127.0.0.1).
    # Injecting VAULTSPEC_GATEWAY_URL ensures the worker always points at
    # the correct gateway regardless of how it was started.
    spawn_env = os.environ.copy()
    spawn_env[GATEWAY_URL_ENV] = settings.gateway_url
    spawn_env["VAULTSPEC_PORT"] = str(settings.port)
    spawn_env["VAULTSPEC_WORKER_PORT"] = str(settings.worker_port)
    spawn_env["VAULTSPEC_WORKER_HOST"] = settings.worker_host
    if settings.internal_token is not None:
        spawn_env[INTERNAL_TOKEN_ENV] = settings.internal_token
    spawn_env[GATEWAY_LIFETIME_ENV] = GATEWAY_LIFETIME_ID
    spawn_env[WORKER_GENERATION_ENV] = str(generation)

    stderr_log_path = _worker_stderr_log_path(worker_port)
    stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
    # POSIX containment seats the worker in a new session/process group at fork;
    # passed explicitly (rather than via ``**kwargs``) so the ``Popen[bytes]``
    # overload is preserved. Windows contributes no spawn-time flag - it assigns
    # the job after spawn.
    new_session = containment is not None and bool(
        containment.spawn_kwargs().get("start_new_session")
    )
    # Freeze-safe worker re-exec: rendered by the runtime's command authority
    # (``python -m vaultspec_a2a.worker`` from source; the binary's own
    # ``run-module`` dispatch when frozen), never assembled interpreter flags.
    worker_command = module_command("vaultspec_a2a.worker")
    with stderr_log_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            worker_command,
            stdout=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            stderr=stderr_handle,
            env=spawn_env,
            start_new_session=new_session,
        )
    return await _await_worker_ready(
        process,
        containment,
        worker_url=worker_url,
        worker_port=worker_port,
        generation=generation,
        worker_command=worker_command,
        stderr_log_path=stderr_log_path,
    )


async def _await_worker_ready(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None,
    *,
    worker_url: str,
    worker_port: int,
    generation: int,
    worker_command: Sequence[str],
    stderr_log_path: Path,
) -> subprocess.Popen[bytes] | None:
    """Seat the spawned worker in its containment and wait for it to be ours.

    Returns the handle once the worker at *worker_url* answers as this gateway's,
    or ``None`` when it exited early or never became ready - reaping the tree in
    both cases, so a ``None`` return never leaves a process on the worker port.

    Split out of :func:`_spawn_worker` because this is exactly the region that
    runs with a live process nobody else can yet reach: the handle exists only in
    this frame until it is returned. A raise here - a cancellation on gateway
    shutdown being the realistic one - would therefore strand the worker as an
    orphan holding the port, which the next spawn refuses as an unidentified
    occupant, wedging the band rather than merely leaking a process. Owning the
    process and owning its failure are the same job, so they are the same
    function.
    """
    try:
        return await _await_worker_ready_inner(
            process,
            containment,
            worker_url=worker_url,
            worker_port=worker_port,
            generation=generation,
            worker_command=worker_command,
            stderr_log_path=stderr_log_path,
        )
    except BaseException:
        await _reap_unready_worker(process, containment)
        raise


async def _await_worker_ready_inner(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None,
    *,
    worker_url: str,
    worker_port: int,
    generation: int,
    worker_command: Sequence[str],
    stderr_log_path: Path,
) -> subprocess.Popen[bytes] | None:
    """Seat and poll the worker; see :func:`_await_worker_ready` for the guard."""
    if containment is not None:
        # Assign the worker to its containment before it boots far enough to spawn
        # any descendant (provider roots, MCP bridges). A failed Windows
        # assignment downgrades to the per-pid fallback rather than failing boot.
        try:
            containment.assign(process.pid)
        except ProcessContainmentError:
            logger.warning(
                "Could not seat worker PID %d in its OS containment; shutdown will"
                " fall back to a per-pid tree kill",
                process.pid,
                exc_info=True,
            )
    logger.info(
        "Worker process spawned (PID %d) via `%s` with stderr at %s",
        process.pid,
        " ".join(worker_command),
        stderr_log_path,
    )

    # Adaptive health polling (PHASE-1e): fast initial probes, exponential
    # backoff to cap.  TCP fast-path skips expensive HTTP checks while the
    # process is still binding its port.
    ready_timeout = settings.worker_ready_timeout_seconds
    started = asyncio.get_event_loop().time()
    deadline = started + ready_timeout
    interval = settings.worker_poll_initial_interval_seconds
    last_log = 0.0  # elapsed seconds at last progress log

    while asyncio.get_event_loop().time() < deadline:
        # Detect OUR spawn dying before probing health. A spawn that crashed on its
        # bind (the port was held by a surviving foreign worker) must be reported as
        # a failed spawn, never as ready off the foreign worker still answering on
        # the port - so the liveness check leads the readiness check.
        if process.poll() is not None:
            detail = _build_worker_restart_detail(
                returncode=process.returncode,
                stderr_log_path=stderr_log_path,
            )
            logger.error(
                "Worker exited prematurely: %s",
                detail,
            )
            # The root died on its own, but a descendant it had already spawned
            # did not necessarily die with it, and one still holding the worker
            # port wedges the next spawn exactly like a timed-out worker's tree
            # would. Reap on the same terms rather than trusting a dead root to
            # mean a dead tree; the reap also waits the handle, so no zombie is
            # left on POSIX.
            await _reap_unready_worker(process, containment)
            return None

        # Ready only when OUR worker answers: the port being open and healthy is not
        # enough when a foreign orphan can squat a shared band port, so readiness
        # requires the responding worker to declare THIS gateway as its target.
        if await _tcp_port_ready(
            "127.0.0.1", worker_port
        ) and await worker_ready_and_ours(worker_url, current_generation=generation):
            elapsed = asyncio.get_event_loop().time() - started
            logger.info(
                "Worker ready at %s (PID %d) in %.1fs",
                worker_url,
                process.pid,
                elapsed,
            )
            return process

        elapsed = asyncio.get_event_loop().time() - started
        if elapsed - last_log >= settings.worker_poll_log_interval_seconds:
            logger.info("Waiting for worker... (%.0fs elapsed)", elapsed)
            last_log = elapsed

        await asyncio.sleep(interval)
        interval = min(
            interval * settings.worker_poll_backoff_factor,
            settings.worker_poll_max_interval_seconds,
        )

    logger.error(
        "Worker failed to become ready within %.0f seconds; stderr_log=%s",
        ready_timeout,
        stderr_log_path,
    )
    await _reap_unready_worker(process, containment)
    return None


async def _spawn_worker_owned(
    worker_url: str,
    worker_port: int,
    *,
    generation: int,
) -> tuple[subprocess.Popen[bytes] | None, ProcessContainment | None]:
    """Spawn a worker, holding its OS containment only while it owns a live tree.

    The single seam both spawn paths - first dispatch and watchdog restart - go
    through, so the ownership contract is enforced in one place rather than
    re-implemented per caller. It allocates the armed desktop profile's
    containment (Compose and development get ``None`` and the unchanged per-pid
    path), spawns, and releases the handle on every outcome except the one that
    transfers ownership: a live process for the caller to shut down later.

    Returns ``(process, containment)``, where a non-``None`` containment is always
    paired with the live process it contains. A failed spawn returns
    ``(None, None)`` - never a containment without a tree, which is the stale
    handle a caller would otherwise have to remember to drop - and a raised spawn
    propagates with the handle already released.
    """
    containment = (
        ProcessContainment.create() if settings.desktop_profile_armed else None
    )
    owned = False
    try:
        process = await _spawn_worker(
            worker_url,
            worker_port,
            containment=containment,
            generation=generation,
        )
        owned = process is not None
        return (process, containment) if owned else (None, None)
    finally:
        # One statement covers all three exits - failed spawn, raised spawn, and
        # the success that hands ownership on - because "release unless ownership
        # transferred" is the whole rule.
        if not owned and containment is not None:
            containment.close()


async def _reap_unready_worker(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None,
) -> None:
    """Reap a worker that spawned but never became ready, tree and all.

    Both bands must escalate and must fell the whole tree, because the caller
    returns ``None`` afterwards - it reports the spawn as failed, and anything
    still alive is by definition an orphan holding the worker port. The next
    spawn then meets its own leftover on that port and refuses it as an
    unidentified occupant, so an incomplete reap here wedges the band rather
    than merely leaking a process.

    Armed desktop: the OS containment fells the tree at once (Job Object or
    process group), and is itself safe when assignment never completed - it
    downgrades to the same per-pid tree kill used below.

    Compose / development: no containment exists, so the shared per-pid tree
    kill does the escalation. A bare ``Popen.terminate`` is not enough - it
    signals only the immediate process, never escalates past a SIGTERM the
    worker may be ignoring, and leaves any descendant behind.

    Either way the handle is waited afterwards so no zombie is left on POSIX.
    """
    if containment is not None:
        await containment.terminate(term_timeout=5.0, kill_timeout=5.0)
    else:
        await kill_pid_tree_async(process.pid, term_timeout=5.0, kill_timeout=5.0)
    with contextlib.suppress(Exception):
        await asyncio.to_thread(process.wait, 5.0)


async def _shutdown_worker_process(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None = None,
) -> None:
    """Shut down the worker child process and its whole tree.

    When *containment* is present (the armed desktop worker), the tree is reaped
    through its OS containment - a POSIX process-group ``killpg`` escalation or a
    Windows Job Object termination - never a parent-pid tree walk. Without a
    containment (Compose / development band), the shared per-pid tree kill
    (Windows ``taskkill /T /F``, POSIX SIGTERM->SIGKILL) is used unchanged.
    """
    if process.poll() is not None:
        if containment is not None:
            containment.close()
        return  # Already exited
    logger.info(
        "Shutting down worker process (PID %d)",
        process.pid,
    )
    if containment is not None:
        await containment.terminate(term_timeout=10.0, kill_timeout=5.0)
    else:
        # Shared async tree-kill (Windows taskkill /T /F, POSIX SIGTERM->SIGKILL);
        # the Popen handle is reaped here since the primitive works by pid.
        await kill_pid_tree_async(process.pid, term_timeout=10.0, kill_timeout=5.0)
    with contextlib.suppress(Exception):
        await asyncio.to_thread(process.wait, 5.0)
    logger.info("Worker process stopped")


# ---------------------------------------------------------------------------
# Lazy worker spawner (PHASE-1a)
# ---------------------------------------------------------------------------


class LazyWorkerSpawner:
    """Defer worker spawn to first dispatch instead of gateway startup.

    Read-only verbs (run listing, run status, preset listing, etc.) only need
    the gateway + database.  The worker is spawned lazily on the first
    write-path call (run start, follow-up message, etc.).

    Thread-safe: an ``asyncio.Lock`` prevents double-spawn when multiple
    dispatches arrive concurrently.
    """

    def __init__(
        self,
        worker_url: str,
        worker_port: int,
        auto_spawn: bool,
    ) -> None:
        """Initialise with worker connection details and spawn policy."""
        self._worker_url = worker_url
        self._worker_port = worker_port
        self._auto_spawn = auto_spawn
        self._process: subprocess.Popen[bytes] | None = None
        # OS containment for the worker tree, created only for the armed desktop
        # gateway that exclusively owns its worker. Compose and development-band
        # spawns leave it None and keep the unchanged per-pid shutdown path.
        self._containment: ProcessContainment | None = None
        self._stderr_log_path = (
            _worker_stderr_log_path(worker_port) if auto_spawn else None
        )
        self._spawned = False
        # Incremented before each spawn, so the value a worker carries names the
        # attempt that produced it. A restart yields a distinct generation even
        # when the port, the host and the gateway are unchanged.
        self._generation = 0
        # A plain increment is not atomic - it loads, adds and stores - so two
        # callers can read the same value and issue one generation twice. The
        # asyncio lock below does not help: the watchdog reaches this from a
        # worker thread, not the event loop.
        self._generation_lock = threading.Lock()
        self._lock = asyncio.Lock()
        # Optional demand-readiness signal wired by the armed desktop gateway. It
        # is fired once, on the authenticated demand path, after the single-flight
        # worker start reaches readiness, so deferred boot reconciliation runs only
        # after real execution demand. Unset (``None``) for Compose and dev, whose
        # boot reconciliation is eager.
        self.demand_ready_event: asyncio.Event | None = None
        if auto_spawn:
            # Startup sweep (once per gateway process, before this port's own log
            # is ever (re)opened): clear stale worker-autospawn stderr logs left
            # behind by past dev-band instances. Best-effort - a sweep failure
            # must never block gateway construction.
            with contextlib.suppress(Exception):
                sweep_orphan_worker_logs(current_worker_port=worker_port)

    @property
    def spawned(self) -> bool:
        """Whether the worker has been spawned (or was already running)."""
        return self._spawned

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        """The worker subprocess handle, if we spawned it."""
        return self._process

    @property
    def stderr_log_path(self) -> Path | None:
        """The worker stderr log path used for gateway-managed spawns."""
        return self._stderr_log_path

    async def ensure_worker(self) -> None:
        """Spawn the worker if not already running.  No-op after first call.

        A spawn that raises leaves this spawner exactly as it found it - no
        process handle, no containment handle, ``spawned`` still ``False`` - and
        leaves nothing of that attempt alive, because the spawn seam reaps its own
        tree and releases its own containment before propagating. The next
        dispatch therefore retries a genuinely fresh spawn, which is the same
        behaviour a spawn that merely returned failure gets. That equivalence is
        the point: ``spawned`` is set after the spawn rather than before it, so it
        can only ever mean "a worker this gateway can use exists", and an
        exception is one of the ways it does not.
        """
        if self._spawned:
            return
        async with self._lock:
            # Double-check after acquiring lock.
            if self._spawned:
                return
            if not self._auto_spawn:
                # Not configured to auto-spawn; attach only to a worker that
                # declares THIS gateway as its target, never a foreign orphan that
                # merely answers /health on the port. Under the armed profile
                # this attach requires the OWNED pairing verdict, which an
                # externally-managed worker can never present - armed without
                # auto-spawn is a misconfiguration and fails closed.
                self._spawned = await worker_ready_and_ours(
                    self._worker_url, current_generation=self._generation
                )
                if not self._spawned:
                    logger.warning(
                        "No worker targeting this gateway at %s and"
                        " auto_spawn_worker=False",
                        self._worker_url,
                    )
                return
            logger.info(
                "First dispatch received — starting worker at %s...",
                self._worker_url,
            )
            # The armed desktop gateway owns its worker exclusively, so it spawns
            # the worker inside an OS containment and reaps the whole tree on
            # shutdown. Other profiles keep the unchanged per-pid path. The spawn
            # seam hands back a containment only alongside the live tree it
            # contains, so these two fields are never separately true.
            generation = self.next_generation()
            self._process, self._containment = await _spawn_worker_owned(
                self._worker_url,
                self._worker_port,
                generation=generation,
            )
            # Mark as spawned even if _spawn_worker found it already running
            # (returns None when a same-gateway worker was already healthy). The
            # fallback probe must confirm the running worker is OURS: a bare health
            # check here would let a refused-eviction foreign orphan (spawn returned
            # None) be adopted as this gateway's worker.
            self._spawned = self._process is not None or (
                await worker_ready_and_ours(
                    self._worker_url, current_generation=self._generation
                )
            )
            if self._spawned:
                logger.info("Worker available — processing dispatch")
            else:
                logger.error(
                    "Failed to spawn worker — dispatches will fail. "
                    "Check worker logs or restart: uv run vaultspec service start"
                )

    @property
    def auto_spawn(self) -> bool:
        """Whether this gateway is configured to spawn/respawn the worker itself.

        ``False`` means the worker is externally managed: the gateway attaches to a
        running worker but must never spawn or restart it (that belongs to whoever
        owns it, e.g. the dev-process registry).
        """
        return self._auto_spawn

    @property
    def worker_url(self) -> str:
        """The worker's base URL."""
        return self._worker_url

    @property
    def worker_port(self) -> int:
        """The worker's port number."""
        return self._worker_port

    def next_generation(self) -> int:
        """Advance and return the spawn generation for a replacement worker.

        The watchdog restarts the worker without going through the lazy spawn
        path, so it takes its generation from here rather than minting one; two
        counters would let a restarted worker claim a generation the gateway
        never issued.
        """
        with self._generation_lock:
            self._generation += 1
            return self._generation

    @property
    def generation(self) -> int:
        """Return the spawn generation of the worker this spawner last started."""
        return self._generation

    def replace_process(
        self,
        process: subprocess.Popen[bytes] | None,
        containment: ProcessContainment | None = None,
    ) -> None:
        """Replace the worker process handle (used by watchdog after restart).

        The restart supplies the new tree's containment so shutdown reaps the
        replacement worker's tree, not a stale one; an adopted worker (no owned
        process) carries no containment.

        The containment being replaced is released here, because this is the one
        place the spawner's reference to it is dropped. The restart path reaches
        this after shutting the old worker down, which already released it - but
        only when the old worker was still running. The commonest restart trigger
        is the opposite case, a worker that already exited, whose handle nothing
        else would ever close. ``close`` is idempotent, so releasing on both paths
        costs nothing and removes the distinction as a thing to get right.
        """
        outgoing = self._containment
        if outgoing is not None and outgoing is not containment:
            outgoing.close()
        self._process = process
        self._containment = containment
        self._spawned = True

    @property
    def containment(self) -> ProcessContainment | None:
        """The OS containment owning the worker tree, if this gateway spawned it."""
        return self._containment

    async def shutdown(self) -> None:
        """Shut down the worker process (and its whole tree) if we spawned it."""
        if self._process is not None:
            await _shutdown_worker_process(self._process, self._containment)
            self._process = None
            self._containment = None


# ---------------------------------------------------------------------------
# Worker watchdog
# ---------------------------------------------------------------------------


class WorkerWatchdog:
    """Background task monitoring worker health and auto-restarting on crash.

    Detection signals:
    1. ``worker_spawner.process.returncode`` is not None -- process crashed.
    2. :meth:`WorkerLiveness.is_stale` -- no contact within the heartbeat
       timeout, so the worker is unresponsive.

    Recovery: exponential backoff restarts (2s, 4s, 8s), circuit breaker
    coordination, and ``WorkerState`` state machine.
    """

    def __init__(
        self,
        spawner: LazyWorkerSpawner,
        circuit_breaker: WorkerCircuitBreaker,
        worker_state: WorkerState,
        app_state: object,
    ) -> None:
        """Initialise watchdog with references to spawner, breaker, and worker state."""
        self._spawner = spawner
        self._cb = circuit_breaker
        self._worker_state = worker_state
        self._app_state = app_state
        # Monotonic timestamp of the last restart CYCLE (not attempt), for the
        # global inter-cycle cooldown that rate-limits a persistent crash signal.
        self._last_restart_cycle_ts: float | None = None
        # Initialise worker state
        self._worker_state.worker_status = WorkerConnectionStatus.PENDING.value
        self._worker_state.worker_restart_count = 0
        self._worker_state.worker_last_restart_reason = None
        self._worker_state.worker_last_restart_detail = None
        self._worker_state.worker_last_restart_started_at = None
        self._worker_state.worker_last_restart_completed_at = None
        self._worker_state.worker_last_restart_succeeded = None
        self._worker_state.worker_last_restart_attempts = 0
        self._worker_state.worker_stderr_log_path = (
            str(spawner.stderr_log_path)
            if spawner.stderr_log_path is not None
            else None
        )

    def _mark_restart_started(self, reason: str, detail: str | None) -> None:
        """Latch restart metadata so callers can observe repair deterministically."""
        self._worker_state.worker_restart_count += 1
        self._worker_state.worker_last_restart_reason = reason
        self._worker_state.worker_last_restart_detail = detail
        self._worker_state.worker_last_restart_started_at = datetime.now(
            UTC
        ).isoformat()
        self._worker_state.worker_last_restart_completed_at = None
        self._worker_state.worker_last_restart_succeeded = None
        self._worker_state.worker_last_restart_attempts = 0

    def _mark_restart_finished(self, succeeded: bool, attempts: int) -> None:
        """Record the terminal outcome of the most recent restart cycle."""
        self._worker_state.worker_last_restart_completed_at = datetime.now(
            UTC
        ).isoformat()
        self._worker_state.worker_last_restart_succeeded = succeeded
        self._worker_state.worker_last_restart_attempts = attempts

    def _heartbeat_stale(self) -> bool:
        """Check if the last heartbeat is older than the timeout threshold."""
        return worker_liveness(self._app_state).is_stale()

    def _process_crashed(self) -> bool:
        """Check if the worker process has exited unexpectedly."""
        proc = self._spawner.process
        return proc is not None and proc.poll() is not None

    async def _probe_worker_ready(self) -> bool:
        """Probe the worker HTTP health endpoint for status promotion checks."""
        return (await probe_worker_health(self._spawner.worker_url)).healthy

    @staticmethod
    def _needs_recovery(*, crashed: bool, stale: bool, http_ready: bool) -> bool:
        """Whether the worker genuinely needs recovery.

        A worker answering ``GET /health`` is alive, so heartbeat-PUSH staleness
        alone (with a healthy HTTP endpoint) is degraded telemetry, not a crash -
        treating it as one is what made the watchdog thrash against a healthy,
        externally-managed worker whose heartbeats were failing (e.g. auth). Only a
        crashed process, or staleness AND an unreachable endpoint, is a real crash.
        """
        return crashed or (stale and not http_ready)

    def _owns_worker(self) -> bool:
        """Whether this gateway may restart the worker (it spawned the process).

        The watchdog must never force the breaker open or spawn a competitor for a
        worker it does not own: an externally-managed worker (``process is None``)
        or a gateway configured not to auto-spawn is reconciled from its HTTP probe
        and its lifecycle left to whoever owns it (the dev-process registry).
        """
        return self._spawner.process is not None and self._spawner.auto_spawn

    def _restart_cooldown_elapsed(self, *, now: float | None = None) -> bool:
        """Whether enough time has passed since the last restart cycle to start one."""
        if self._last_restart_cycle_ts is None:
            return True
        current = now if now is not None else time.monotonic()
        return (
            current - self._last_restart_cycle_ts
        ) >= settings.watchdog_restart_cooldown_seconds

    async def run(self) -> None:
        """Main watchdog loop — runs until cancelled.

        A failing tick must not end the supervisor. The loop exists to recover a
        worker that has gone wrong, and the spawn it performs to do that is the
        most likely thing in it to raise - so an unguarded tick made the first
        failed recovery the last one, leaving the worker permanently unsupervised
        with the circuit breaker held open by the cycle that died. The tick is
        contained instead: the failure is logged and the next poll retries it,
        which is the same treatment a restart that merely failed already gets.

        Containment is per tick rather than a restart of the whole loop, because
        the state a retry needs - the restart cooldown, the attempt counters, the
        breaker - lives on this instance and survives a failed tick. Re-running
        the loop from outside would either discard that state or duplicate the
        backoff logic it encodes.

        Cancellation still stops the loop, and it is the only thing that stops it
        quietly. Any other exit is logged as critical before it propagates: a
        watchdog can fail, but it must not fail silently, or the gateway reports a
        supervised worker it is no longer supervising.
        """
        try:
            while True:
                await asyncio.sleep(settings.watchdog_poll_interval_seconds)
                try:
                    await self._tick()
                except Exception:
                    logger.exception(
                        "Worker watchdog tick failed; the watchdog stays active and"
                        " retries on the next poll"
                    )
        except asyncio.CancelledError:
            logger.info("Worker watchdog stopped")
        except BaseException:
            logger.critical(
                "Worker watchdog terminated by an unhandled exception; the worker"
                " is no longer supervised and will not be restarted automatically",
                exc_info=True,
            )
            raise

    async def _tick(self) -> None:
        """One watchdog poll: detect, reconcile status, and restart only when owned."""
        # Don't monitor before first dispatch triggers a spawn.
        if not self._spawner.spawned:
            return

        # --- Detection ---
        http_ready = await self._probe_worker_ready()
        crashed = self._process_crashed()
        stale = self._heartbeat_stale()
        needs_recovery = self._needs_recovery(
            crashed=crashed, stale=stale, http_ready=http_ready
        )

        # --- Adopted / externally-managed worker: reconcile purely from the probe ---
        # We hold no process handle (same-gateway adoption returns None, or the worker
        # is owned by the dev-process registry), so there is no restart path that could
        # ever flip a stuck "down" back up. The owned-worker state machine below keeps a
        # "down" worker down until a real restart recovers it - correct for a worker we
        # can restart, but for an adopted one it would freeze a healthy worker's status
        # at "down"/"pending" and make plain /health readiness lie. Track the live HTTP
        # probe every tick instead, so an adopted healthy worker reaches "up".
        if self._spawner.process is None:
            self._worker_state.worker_status = (
                WorkerConnectionStatus.UP.value
                if http_ready
                else WorkerConnectionStatus.DOWN.value
            )
            return

        # Promote to "up" only after a positive worker health probe.
        if self._worker_state.worker_status == WorkerConnectionStatus.PENDING:
            if http_ready and not needs_recovery:
                self._worker_state.worker_status = WorkerConnectionStatus.UP.value
                return
            if not needs_recovery:
                return

        # --- Healthy / degraded-but-alive: reconcile status, never restart ---
        if not needs_recovery:
            if self._worker_state.worker_status == WorkerConnectionStatus.UP:
                return
            # Recovered from a transient state (a "down" worker stays down until a
            # real recovery flips it).
            if self._worker_state.worker_status != WorkerConnectionStatus.DOWN:
                self._worker_state.worker_status = WorkerConnectionStatus.UP.value
            return

        # --- Needs recovery ---
        # The gateway only restarts a worker it OWNS. For an external/adopted worker
        # (or a no-auto-spawn deployment) it reports the truth and leaves recovery to
        # the owner - never force-opening the breaker or spawning a competitor.
        if not self._owns_worker():
            self._worker_state.worker_status = (
                WorkerConnectionStatus.UP.value
                if http_ready
                else WorkerConnectionStatus.DOWN.value
            )
            return

        # Global inter-cycle cooldown: a persistent crash signal cannot spin restart
        # cycles faster than the configured cooldown.
        if not self._restart_cooldown_elapsed():
            return

        reason = "process_exited" if crashed else "heartbeat_stale"
        proc = self._spawner.process
        detail = None
        if crashed:
            detail = _build_worker_restart_detail(
                returncode=proc.returncode,
                stderr_log_path=self._spawner.stderr_log_path,
            )
        logger.error(
            "Worker crash detected: %s%s — initiating restart",
            reason,
            f" ({detail})" if detail else "",
        )
        self._worker_state.worker_status = WorkerConnectionStatus.RESTARTING.value
        self._mark_restart_started(reason, detail)

        # Force circuit breaker open so dispatches return 503.
        self._cb.force_open()

        # --- Restart with exponential backoff ---
        # Stamp the cycle even when the restart raises, so the inter-cycle
        # cooldown throttles a failing cycle exactly as it throttles a failed one.
        # Without this the loop's per-tick failure containment would retry a
        # raising spawn at the poll interval instead of the cooldown.
        try:
            restarted, attempts = await self._attempt_restart()
        finally:
            self._last_restart_cycle_ts = time.monotonic()
        self._mark_restart_finished(restarted, attempts)
        if restarted:
            self._cb.record_success()
            self._worker_state.worker_status = WorkerConnectionStatus.UP.value
            logger.info("Worker restarted successfully")
        else:
            self._worker_state.worker_status = WorkerConnectionStatus.DOWN.value
            logger.critical(
                "Worker restart failed after %d attempts — "
                "manual intervention required. "
                "Run: uv run vaultspec service start",
                settings.watchdog_max_retries,
            )

    async def _attempt_restart(self) -> tuple[bool, int]:
        """Try to restart the worker with exponential backoff.

        Returns ``(succeeded, attempts)`` for the current restart cycle.
        """
        for attempt in range(settings.watchdog_max_retries):
            self._worker_state.worker_last_restart_attempts = attempt + 1
            delay = settings.watchdog_backoff_base_seconds * (2**attempt)
            logger.info(
                "Restart attempt %d/%d — waiting %.0fs...",
                attempt + 1,
                settings.watchdog_max_retries,
                delay,
            )
            await asyncio.sleep(delay)

            # Clean up the old process handle and reap its whole tree through the
            # containment it was spawned in (if any).
            old_proc = self._spawner.process
            if old_proc is not None and old_proc.returncode is None:
                await _shutdown_worker_process(old_proc, self._spawner.containment)

            # Spawn a new worker inside a fresh containment (armed desktop only),
            # and hand it to the spawner so shutdown reaps the replacement's tree.
            # A restart that fails hands back no containment either, so a retry
            # loop cannot accumulate one handle per attempt.
            new_proc, new_containment = await _spawn_worker_owned(
                self._spawner.worker_url,
                self._spawner.worker_port,
                generation=self._spawner.next_generation(),
            )
            if new_proc is not None:
                self._spawner.replace_process(new_proc, new_containment)
                return True, attempt + 1

            # Check if an external worker came up. Adoption still requires
            # provenance: under the armed profile the authenticated pairing
            # verdict, elsewhere the declared-gateway_url signal - a bare
            # health 200 from a stranger on the port is not an adoptable
            # worker.
            if await worker_ready_and_ours(
                self._spawner.worker_url,
                current_generation=self._spawner.generation,
            ):
                self._spawner.replace_process(None)
                return True, attempt + 1

        return False, settings.watchdog_max_retries
