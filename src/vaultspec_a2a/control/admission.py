"""Bounded, expiring run-admission reservations for the desktop gateway.

The two-stage desktop admission protocol splits the single run-start verb into a
``prepare`` that reserves a bounded, expiring admission slot and a ``commit`` that
binds the dashboard-minted actor tokens to a stable run under that reservation.
An explicit ``release`` frees only an uncommitted reservation. This module owns
the reservation half of the protocol used by
:mod:`vaultspec_a2a.api.routes.gateway`.

A prepare validates the request's required roles, triggers the gateway-owned
worker's single-flight startup through the injected demand seam, probes execution
readiness, and - only when execution is ready and a slot is free under the hard
reservation bound - records an expiring reservation with the prepared-request
digest. It accepts no actor token, creates no durable run, and
spawns no run-owned child: the only process it may bring up is the gateway's own
lazy worker, which is shared, not run-owned. A reservation that is never committed
simply expires and frees its slot. Commit accepts only the exact prepared request
and role set; mismatches leave the reservation active for a valid retry.

The broker holds only reservation bookkeeping. Minting actor tokens, creating the
durable run, and dispatching it belong to the route that consumes a committed
reservation. The single worker event loop makes the lock an ordering guard: the
capacity check and the reservation insert are one atomic critical section, so
concurrent prepares can never oversubscribe the bound even while they share one
single-flight worker start.
"""

from __future__ import annotations

import asyncio
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..api.schemas.gateway import (
        ProviderEligibility,
        RunAdmission,
        WorkerLifecycleState,
    )

__all__ = [
    "AdmissionBroker",
    "AdmissionReadiness",
    "CommitOutcome",
    "PrepareOutcome",
    "ReservationState",
]

# Defaults: the reservation bound mirrors the worker's concurrent-run capacity,
# and a reservation lives long enough for the dashboard to round-trip a commit but
# is short enough that an abandoned prepare frees its slot promptly.
_DEFAULT_MAX_RESERVATIONS = 5
_DEFAULT_RESERVATION_TTL_SECONDS = 120.0
_MAX_REQUIRED_ROLES = 64

_REASON_NO_ROLES = "prepare requires at least one required role"
_REASON_TOO_MANY_ROLES = (
    f"prepare carries more than the {_MAX_REQUIRED_ROLES}-role maximum"
)
_REASON_CAPACITY = "run-admission reservation capacity is exhausted"
_REASON_UNKNOWN = "no active reservation matches the supplied reservation id"
_REASON_NOT_ACTIVE = "reservation is expired, released, or already committed"
_REASON_NOT_READY = "run admission is not execution-ready"
_REASON_BINDING_MISMATCH = "commit does not match the prepared request"
_REASON_ROLES_MISMATCH = (
    "actor token roles do not exactly match the prepared reservation"
)


class ReservationState(StrEnum):
    """The lifecycle rung of one admission reservation."""

    ACTIVE = "active"
    COMMITTING = "committing"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class AdmissionReadiness:
    """Execution-readiness facts probed once during a prepare.

    Reports the worker's rung on the cold-to-execution ladder, whether any
    subprocess provider resolves on this host, and the composed run-admission
    verdict. Prepare is fail-closed: any verdict other than execution-ready
    refuses the reservation before capacity is assigned.
    """

    worker_state: WorkerLifecycleState
    provider_eligibility: ProviderEligibility
    eligible_providers: tuple[str, ...]
    run_admission: RunAdmission
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrepareOutcome:
    """The result of a :meth:`AdmissionBroker.prepare` call.

    ``admitted`` is ``True`` only when a reservation slot was recorded under the
    hard bound. A successful prepare returns both its reservation id and the
    non-secret lease id the caller binds before commit. A refused prepare carries
    neither. ``readiness`` is always populated with the facts probed during the
    attempt so a caller can surface them even on a capacity refusal.
    """

    admitted: bool
    reservation_id: str | None
    lease_id: str | None
    required_roles: tuple[str, ...]
    expires_at: str | None
    readiness: AdmissionReadiness
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    """The result of a :meth:`AdmissionBroker.commit` call.

    ``committed`` is ``True`` only when an active, unexpired reservation entered
    the committing state. ``lease_id`` is the non-secret, run-scoped identity
    minted at prepare. The caller completes consumption only after the durable
    run exists. A refused commit carries the reason and no lease.
    """

    committed: bool
    reservation_id: str
    required_roles: tuple[str, ...] = ()
    lease_id: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class _Reservation:
    """Internal reservation bookkeeping; never leaves the broker."""

    reservation_id: str
    lease_id: str
    required_roles: tuple[str, ...]
    binding_digest: str
    expires_monotonic: float
    expires_at_iso: str
    state: ReservationState = ReservationState.ACTIVE


class AdmissionBroker:
    """Serialise bounded, expiring run-admission reservations.

    One broker per gateway process, seated on ``app.state`` alongside the drain
    gate. The prepare path is the only place worker demand is triggered before a
    durable run exists; commit authorizes one transition, but the reservation is
    consumed only after the route reports that its durable run exists.
    """

    def __init__(
        self,
        *,
        max_reservations: int = _DEFAULT_MAX_RESERVATIONS,
        reservation_ttl_seconds: float = _DEFAULT_RESERVATION_TTL_SECONDS,
    ) -> None:
        self._max = max(1, max_reservations)
        self._ttl = reservation_ttl_seconds
        self._reservations: dict[str, _Reservation] = {}
        self._lock = asyncio.Lock()

    async def prepare(
        self,
        *,
        required_roles: list[str],
        ensure_worker: Callable[[], Awaitable[None]],
        probe_readiness: Callable[[], Awaitable[AdmissionReadiness]],
        binding_digest: str,
    ) -> PrepareOutcome:
        """Reserve a bounded admission slot after triggering worker startup.

        Validates the required-role set, triggers the gateway-owned worker's
        single-flight start through *ensure_worker*, probes execution readiness
        through *probe_readiness*, and - readiness having been probed before any
        capacity is assigned - records an expiring reservation only when a slot is
        free under the hard bound. No token is accepted and no run is created; the
        worker is the gateway's own, never a run-owned child.
        """
        roles = tuple(required_roles)
        if not roles:
            return PrepareOutcome(
                admitted=False,
                reservation_id=None,
                lease_id=None,
                required_roles=roles,
                expires_at=None,
                readiness=await probe_readiness(),
                reason=_REASON_NO_ROLES,
            )
        if len(roles) > _MAX_REQUIRED_ROLES:
            return PrepareOutcome(
                admitted=False,
                reservation_id=None,
                lease_id=None,
                required_roles=roles,
                expires_at=None,
                readiness=await probe_readiness(),
                reason=_REASON_TOO_MANY_ROLES,
            )

        # Trigger the single-flight worker start and probe readiness BEFORE any
        # capacity is assigned (the ADR's "probe readiness before assigning run
        # capacity"). Concurrent prepares each await the spawner's own single
        # flight, so exactly one worker is created no matter how many prepare.
        await ensure_worker()
        readiness = await probe_readiness()
        if (
            readiness.worker_state.value != "ready"
            or readiness.provider_eligibility.value != "eligible"
            or readiness.run_admission.value != "ready"
        ):
            return PrepareOutcome(
                admitted=False,
                reservation_id=None,
                lease_id=None,
                required_roles=roles,
                expires_at=None,
                readiness=readiness,
                reason=_REASON_NOT_READY,
            )

        loop = asyncio.get_running_loop()
        now = loop.time()
        async with self._lock:
            self._sweep_expired(now)
            if len(self._reservations) >= self._max:
                return PrepareOutcome(
                    admitted=False,
                    reservation_id=None,
                    lease_id=None,
                    required_roles=roles,
                    expires_at=None,
                    readiness=readiness,
                    reason=_REASON_CAPACITY,
                )
            reservation_id = f"resv-{secrets.token_hex(16)}"
            lease_id = f"lease-{secrets.token_hex(16)}"
            expires_at_iso = (
                datetime.now(UTC) + timedelta(seconds=self._ttl)
            ).isoformat()
            self._reservations[reservation_id] = _Reservation(
                reservation_id=reservation_id,
                lease_id=lease_id,
                required_roles=roles,
                binding_digest=binding_digest,
                expires_monotonic=now + self._ttl,
                expires_at_iso=expires_at_iso,
            )
        return PrepareOutcome(
            admitted=True,
            reservation_id=reservation_id,
            lease_id=lease_id,
            required_roles=roles,
            expires_at=expires_at_iso,
            readiness=readiness,
        )

    async def commit(
        self,
        reservation_id: str,
        *,
        binding_digest: str,
        presented_roles: set[str],
    ) -> CommitOutcome:
        """Authorize an active reservation without consuming it before durability.

        The reservation enters ``committing`` and continues to occupy capacity
        until :meth:`complete_commit` observes the durable run. A failed creation
        calls :meth:`abort_commit`, restoring the same reservation for an exact
        retry. The lease identity was minted at prepare and remains stable.
        """
        loop = asyncio.get_running_loop()
        now = loop.time()
        async with self._lock:
            self._sweep_expired(now)
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                return CommitOutcome(
                    committed=False,
                    reservation_id=reservation_id,
                    reason=_REASON_UNKNOWN,
                )
            if reservation.state not in {
                ReservationState.ACTIVE,
                ReservationState.COMMITTING,
            }:
                return CommitOutcome(
                    committed=False,
                    reservation_id=reservation_id,
                    reason=_REASON_NOT_ACTIVE,
                )
            if reservation.binding_digest != binding_digest:
                return CommitOutcome(
                    committed=False,
                    reservation_id=reservation_id,
                    reason=_REASON_BINDING_MISMATCH,
                )
            if presented_roles != set(reservation.required_roles):
                return CommitOutcome(
                    committed=False,
                    reservation_id=reservation_id,
                    reason=_REASON_ROLES_MISMATCH,
                )
            reservation.state = ReservationState.COMMITTING
        return CommitOutcome(
            committed=True,
            reservation_id=reservation_id,
            required_roles=reservation.required_roles,
            lease_id=reservation.lease_id,
        )

    async def complete_commit(self, reservation_id: str, lease_id: str) -> bool:
        """Consume a reservation after its exact durable run exists.

        ``ACTIVE`` is accepted as well as ``COMMITTING`` so an exact durable
        replay can repair a prior exception path that conservatively restored
        the reservation before it could observe the committed row.
        """
        async with self._lock:
            reservation = self._reservations.get(reservation_id)
            if (
                reservation is None
                or reservation.state
                not in {ReservationState.ACTIVE, ReservationState.COMMITTING}
                or reservation.lease_id != lease_id
            ):
                return False
            reservation.state = ReservationState.COMMITTED
            del self._reservations[reservation_id]
            return True

    async def abort_commit(self, reservation_id: str, lease_id: str) -> bool:
        """Restore a failed pre-durability commit for an exact retry."""
        now = asyncio.get_running_loop().time()
        async with self._lock:
            reservation = self._reservations.get(reservation_id)
            if (
                reservation is None
                or reservation.state is not ReservationState.COMMITTING
                or reservation.lease_id != lease_id
            ):
                return False
            if reservation.expires_monotonic <= now:
                reservation.state = ReservationState.EXPIRED
                del self._reservations[reservation_id]
            else:
                reservation.state = ReservationState.ACTIVE
            return True

    async def release(self, reservation_id: str, *, binding_digest: str) -> bool:
        """Release an active reservation without committing it; idempotent.

        The explicit counterpart to expiry: a failed commit, a cancellation, or a
        caller-observed timeout frees the slot immediately rather than waiting out
        the reservation's time-to-live.
        """
        async with self._lock:
            reservation = self._reservations.get(reservation_id)
            if (
                reservation is not None
                and reservation.state is ReservationState.ACTIVE
                and hmac.compare_digest(reservation.binding_digest, binding_digest)
            ):
                reservation.state = ReservationState.RELEASED
                del self._reservations[reservation_id]
                return True
            return False

    def _sweep_expired(self, now: float) -> None:
        """Drop every reservation past its expiry. Caller holds the lock."""
        expired = [
            reservation_id
            for reservation_id, reservation in self._reservations.items()
            if reservation.state
            in {ReservationState.ACTIVE, ReservationState.COMMITTING}
            and reservation.expires_monotonic <= now
        ]
        for reservation_id in expired:
            self._reservations[reservation_id].state = ReservationState.EXPIRED
            del self._reservations[reservation_id]

    @property
    def active_reservation_count(self) -> int:
        """Number of reservations currently occupying the bound (not swept)."""
        return len(self._reservations)

    @property
    def max_reservations(self) -> int:
        """The hard reservation bound."""
        return self._max

    def is_active(self, reservation_id: str) -> bool:
        """Whether *reservation_id* is currently an active, unswept reservation."""
        reservation = self._reservations.get(reservation_id)
        return reservation is not None and reservation.state is ReservationState.ACTIVE
