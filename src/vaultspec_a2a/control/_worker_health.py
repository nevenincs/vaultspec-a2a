"""Worker health, liveness, and existing-process ownership probes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError

from ..lifecycle.pairing import (
    WorkerPairingVerdict,
    classify_worker_pairing,
    eviction_is_authorized,
)
from .config import settings
from .worker_status import WorkerConnectionStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import httpx

__all__ = [
    "GATEWAY_LIFETIME_ENV",
    "GATEWAY_LIFETIME_ID",
    "WORKER_GENERATION_ENV",
    "WorkerHealthProbe",
    "WorkerLiveness",
    "WorkerState",
    "_build_worker_restart_detail",
    "_desktop_worker_port_clear",
    "_evict_stale_worker",
    "_internal_auth_headers",
    "_read_log_tail",
    "_shared_worker_port_clear",
    "_tcp_port_ready",
    "_worker_stderr_log_path",
    "probe_worker_health",
    "sweep_orphan_worker_logs",
    "worker_liveness",
    "worker_ready_and_ours",
]

logger = logging.getLogger("vaultspec_a2a.control.worker_management")
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

    A refused connection is decisive evidence of absence: the transport reached
    the port and nothing accepted. A connect timeout is different; under host
    saturation the live loopback worker may not accept inside this observation's
    budget. It therefore joins read timeouts, exhausted client pools, and dropped
    responses as an unknown observation rather than proof that the worker vanished.
    """
    import httpx

    if isinstance(exc, httpx.ConnectTimeout):
        return True
    if isinstance(exc, httpx.ConnectError):
        return False
    return isinstance(exc, httpx.TransportError)


def _same_gateway(worker_target: object, our_gateway: str) -> bool:
    """Whether a worker explicitly declares *this* gateway as its target."""
    return (
        isinstance(worker_target, str)
        and bool(worker_target.strip())
        and worker_target.rstrip("/") == our_gateway.rstrip("/")
    )


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
    as ``OWNED`` is adopted; missing, blank, or foreign evidence fails closed.
    Unarmed profiles require an exact declared ``gateway_url`` match. Registry-
    and Compose-managed workers publish that current evidence through health.

    An occupant that answered but reported nothing readable is not ours under
    either profile. This is the opposite reading from the spawn path, which
    treats the same occupant as a reason NOT to spawn - deliberately so: "some
    process holds this port" and "this process is provably mine" are different
    questions, and the safe answer to the first is the unsafe answer to the
    second. Missing, blank and unreadable targets are all absence of evidence.
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


async def _desktop_worker_port_clear(
    worker_url: str, worker_port: int, generation: int
) -> bool:
    """Adopt or evict only a proven desktop worker occupying this port."""
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
            return False
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
                return False
        else:
            logger.error(
                "Worker port %d is held by a process this gateway cannot "
                "adopt or evict (pairing verdict: %s) — refusing to spawn "
                "(conflict, no adoption, no eviction)",
                worker_port,
                verdict.value,
            )
            return False
    return True


async def _shared_worker_port_clear(worker_url: str, worker_port: int) -> bool:
    """Handle a same-gateway worker or a stale foreign development worker."""
    existing = await probe_worker_health(worker_url)
    if existing.healthy:
        if existing.body is None:
            logger.error(
                "Worker port %d is held by a healthy worker with unreadable "
                "pairing evidence — refusing to spawn or adopt",
                worker_port,
            )
            return False
        declared_target = existing.body.get("gateway_url")
        if not isinstance(declared_target, str) or not declared_target.strip():
            logger.error(
                "Worker port %d is held by a healthy worker without an exact "
                "gateway target — refusing to spawn, adopt, or evict",
                worker_port,
            )
            return False
        if _same_gateway(
            declared_target,
            settings.gateway_url,
        ):
            logger.info(
                "Worker already running at %s targeting this gateway (%s)"
                " — skipping auto-spawn",
                worker_url,
                settings.gateway_url,
            )
            return False
        # A stale orphan from a dead dev-band gateway is squatting the worker
        # port: it heartbeats a gateway that no longer exists and would never
        # be re-pointed. Evict it and spawn a fresh worker wired to THIS
        # gateway.
        logger.warning(
            "Worker at %s targets a foreign gateway (%s != %s) — evicting the"
            " stale orphan before spawning a fresh worker",
            worker_url,
            declared_target,
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
            return False

    return True
