"""Shared durable ownership for gateway-to-worker control dispatches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, TypedDict, Unpack, cast
from uuid import uuid4

from ..database import (
    ControlActionModel,
    ControlActionReservation,
    ThreadModel,
    acquire_control_action_lease,
    commit_control_action_lease,
    release_control_action_lease,
    reserve_control_action,
    thread_write_expectation,
)
from ..thread.dispatch_policy import FailureType
from ..thread.enums import RECOVERY_ACTION_TYPES, ControlActionType, RecoveryCondition
from .dispatch_receipts import prepare_graph_action_receipt
from .recovery import record_recovery_failure

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import RunWriteAuthority
    from ..database.thread_repository import ThreadWriteExpectation

__all__ = [
    "CONTROL_ACTION_LEASE_TTL",
    "ControlActionClaim",
    "ControlActionClaimRequest",
    "DispatchFailureDisposition",
    "finalize_control_action_acceptance",
    "prepare_control_action_claim",
    "record_dispatch_failure",
]


CONTROL_ACTION_LEASE_TTL = timedelta(seconds=90)
"""Fresh ownership window before an unapplied dispatch may be redriven."""

_DEFINITE_NON_DELIVERY = frozenset(
    {FailureType.CIRCUIT_OPEN, FailureType.AT_CAPACITY, FailureType.REJECTED}
)


_MISSING_FIELD = object()
_CONTROL_ACTION_CLAIM_FIELDS = (
    "action_id",
    "dispatch_id",
    "created",
    "payload_matches",
    "acquired",
    "authority_matches",
    "applied",
    "result_status",
    "claim_token",
)
_CONTROL_ACTION_CLAIM_DEFAULTS = (_MISSING_FIELD,) * len(_CONTROL_ACTION_CLAIM_FIELDS)
_CONTROL_ACTION_CLAIM_REQUEST_FIELDS = (
    "thread_id",
    "action_type",
    "idempotency_key",
    "payload",
    "dispatch_id",
    "request_id",
    "worker_generation",
    "now",
    "lease_ttl",
    "write_expectation",
    "recovery_timeout_seconds",
    "recovery_deadline_at",
)
_CONTROL_ACTION_CLAIM_REQUEST_DEFAULTS = (_MISSING_FIELD,) * 5 + (
    None,
    0,
    None,
    CONTROL_ACTION_LEASE_TTL,
    None,
    None,
    None,
)


def _bind_legacy_fields(
    args: tuple[object, ...],
    options: Mapping[str, object],
    names: tuple[str, ...],
    defaults: tuple[object, ...],
) -> tuple[object, ...]:
    """Bind the original dataclass field order from args and keyword fields."""
    if len(args) > len(names):
        raise TypeError(
            f"expected at most {len(names)} positional arguments, got {len(args)}"
        )
    unknown = next((name for name in options if name not in names), None)
    if unknown is not None:
        raise TypeError(f"unexpected keyword argument {unknown!r}")
    duplicate = next(
        (name for name in names[: len(args)] if name in options),
        None,
    )
    if duplicate is not None:
        raise TypeError(f"multiple values for argument {duplicate!r}")
    return tuple(
        args[index] if index < len(args) else options.get(name, defaults[index])
        for index, name in enumerate(names)
    )


def _required_field(name: str, value: object) -> object:
    if value is _MISSING_FIELD:
        raise TypeError(f"missing required argument {name!r}")
    return value


@dataclass(frozen=True, slots=True)
class _ControlActionClaimIdentity:
    action_id: str
    dispatch_id: str


@dataclass(frozen=True, slots=True)
class _ControlActionClaimState:
    created: bool
    payload_matches: bool
    acquired: bool
    authority_matches: bool
    applied: bool
    result_status: str


@dataclass(frozen=True, slots=True)
class _ControlActionClaimLease:
    claim_token: str | None


class _ControlActionClaimOptions(TypedDict, total=False):
    action_id: str
    dispatch_id: str
    created: bool
    payload_matches: bool
    acquired: bool
    authority_matches: bool
    applied: bool
    result_status: str
    claim_token: str | None


@dataclass(frozen=True, slots=True, init=False)
class ControlActionClaim:
    """Immutable caller view of a durable reservation and lease attempt."""

    _identity: _ControlActionClaimIdentity
    _state: _ControlActionClaimState
    _lease: _ControlActionClaimLease

    def __init__(
        self,
        *args: object,
        **options: Unpack[_ControlActionClaimOptions],
    ) -> None:
        values = _bind_legacy_fields(
            args,
            options,
            _CONTROL_ACTION_CLAIM_FIELDS,
            _CONTROL_ACTION_CLAIM_DEFAULTS,
        )
        object.__setattr__(
            self,
            "_identity",
            _ControlActionClaimIdentity(
                action_id=cast("str", _required_field("action_id", values[0])),
                dispatch_id=cast("str", _required_field("dispatch_id", values[1])),
            ),
        )
        object.__setattr__(
            self,
            "_state",
            _ControlActionClaimState(
                created=cast("bool", _required_field("created", values[2])),
                payload_matches=cast(
                    "bool", _required_field("payload_matches", values[3])
                ),
                acquired=cast("bool", _required_field("acquired", values[4])),
                authority_matches=cast(
                    "bool", _required_field("authority_matches", values[5])
                ),
                applied=cast("bool", _required_field("applied", values[6])),
                result_status=cast("str", _required_field("result_status", values[7])),
            ),
        )
        object.__setattr__(
            self,
            "_lease",
            _ControlActionClaimLease(cast("str | None", values[8])),
        )

    @property
    def action_id(self) -> str:
        return self._identity.action_id

    @property
    def dispatch_id(self) -> str:
        return self._identity.dispatch_id

    @property
    def created(self) -> bool:
        return self._state.created

    @property
    def payload_matches(self) -> bool:
        return self._state.payload_matches

    @property
    def acquired(self) -> bool:
        return self._state.acquired

    @property
    def authority_matches(self) -> bool:
        return self._state.authority_matches

    @property
    def applied(self) -> bool:
        return self._state.applied

    @property
    def result_status(self) -> str:
        return self._state.result_status

    @property
    def claim_token(self) -> str | None:
        return self._lease.claim_token


@dataclass(frozen=True, slots=True)
class _ControlActionRequestIdentity:
    thread_id: str
    action_type: ControlActionType | str
    idempotency_key: str
    payload: dict[str, object] | None
    dispatch_id: str
    request_id: str | None
    worker_generation: int


@dataclass(frozen=True, slots=True)
class _ControlActionRequestTiming:
    now: datetime | None
    lease_ttl: timedelta


@dataclass(frozen=True, slots=True)
class _ControlActionRequestRecovery:
    write_expectation: ThreadWriteExpectation | None
    recovery_timeout_seconds: int | None
    recovery_deadline_at: datetime | None


class _ControlActionClaimRequestOptions(TypedDict, total=False):
    thread_id: str
    action_type: ControlActionType | str
    idempotency_key: str
    payload: dict[str, object] | None
    dispatch_id: str
    request_id: str | None
    worker_generation: int
    now: datetime | None
    lease_ttl: timedelta
    write_expectation: ThreadWriteExpectation | None
    recovery_timeout_seconds: int | None
    recovery_deadline_at: datetime | None


@dataclass(frozen=True, slots=True, init=False)
class ControlActionClaimRequest:
    """Accepted dispatch identity, recovery deadline, and receipt expectation."""

    _identity: _ControlActionRequestIdentity
    _timing: _ControlActionRequestTiming
    _recovery: _ControlActionRequestRecovery

    def __init__(
        self,
        *args: object,
        **options: Unpack[_ControlActionClaimRequestOptions],
    ) -> None:
        values = _bind_legacy_fields(
            args,
            options,
            _CONTROL_ACTION_CLAIM_REQUEST_FIELDS,
            _CONTROL_ACTION_CLAIM_REQUEST_DEFAULTS,
        )
        object.__setattr__(
            self,
            "_identity",
            _ControlActionRequestIdentity(
                thread_id=cast("str", _required_field("thread_id", values[0])),
                action_type=cast(
                    "ControlActionType | str",
                    _required_field("action_type", values[1]),
                ),
                idempotency_key=cast(
                    "str", _required_field("idempotency_key", values[2])
                ),
                payload=cast(
                    "dict[str, object] | None",
                    _required_field("payload", values[3]),
                ),
                dispatch_id=cast("str", _required_field("dispatch_id", values[4])),
                request_id=cast("str | None", values[5]),
                worker_generation=cast("int", values[6]),
            ),
        )
        object.__setattr__(
            self,
            "_timing",
            _ControlActionRequestTiming(
                now=cast("datetime | None", values[7]),
                lease_ttl=cast("timedelta", values[8]),
            ),
        )
        object.__setattr__(
            self,
            "_recovery",
            _ControlActionRequestRecovery(
                write_expectation=cast("ThreadWriteExpectation | None", values[9]),
                recovery_timeout_seconds=cast("int | None", values[10]),
                recovery_deadline_at=cast("datetime | None", values[11]),
            ),
        )

    @property
    def thread_id(self) -> str:
        return self._identity.thread_id

    @property
    def action_type(self) -> ControlActionType | str:
        return self._identity.action_type

    @property
    def idempotency_key(self) -> str:
        return self._identity.idempotency_key

    @property
    def payload(self) -> dict[str, object] | None:
        return self._identity.payload

    @property
    def dispatch_id(self) -> str:
        return self._identity.dispatch_id

    @property
    def request_id(self) -> str | None:
        return self._identity.request_id

    @property
    def worker_generation(self) -> int:
        return self._identity.worker_generation

    @property
    def now(self) -> datetime | None:
        return self._timing.now

    @property
    def lease_ttl(self) -> timedelta:
        return self._timing.lease_ttl

    @property
    def write_expectation(self) -> ThreadWriteExpectation | None:
        return self._recovery.write_expectation

    @property
    def recovery_timeout_seconds(self) -> int | None:
        return self._recovery.recovery_timeout_seconds

    @property
    def recovery_deadline_at(self) -> datetime | None:
        return self._recovery.recovery_deadline_at


class DispatchFailureDisposition(StrEnum):
    """Exact durable result of settling one failed dispatch attempt."""

    DEFINITE_NON_DELIVERY = "definite_non_delivery"
    AMBIGUOUS_DELIVERY = "ambiguous_delivery"
    AUTHORITY_LOST = "authority_lost"
    DEADLINE_EXPIRED = "deadline_expired"
    APPLICATION_WON = "application_won"


def _resolved_recovery_deadline(
    action_type: ControlActionType,
    instant: datetime,
    timeout_seconds: int | None,
    deadline_at: datetime | None,
) -> datetime | None:
    if action_type not in RECOVERY_ACTION_TYPES:
        if timeout_seconds is not None or deadline_at is not None:
            raise ValueError("non-recoverable action cannot carry a recovery deadline")
        return None
    if (timeout_seconds is None) == (deadline_at is None):
        raise ValueError(
            "recoverable action requires exactly one run timeout or deadline"
        )
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise ValueError("recovery_timeout_seconds must be positive")
        deadline_at = instant + timedelta(seconds=timeout_seconds)
    if deadline_at is None or deadline_at <= instant:
        raise ValueError("recovery deadline must be later than acceptance")
    return deadline_at


async def _claim_reserved_action(
    db: AsyncSession,
    reservation: ControlActionReservation,
    action_type: ControlActionType,
    instant: datetime,
    lease_ttl: timedelta,
) -> tuple[str | None, bool, bool]:
    action = reservation.action
    authority_matches = action_type not in RECOVERY_ACTION_TYPES or (
        action.recovery_deadline_at is not None
        and action.recovery_deadline_at > instant
    )
    if not authority_matches or not reservation.payload_matches or action.applied_at:
        return None, False, authority_matches
    claim_token = uuid4().hex
    acquired = await acquire_control_action_lease(
        db,
        action.id,
        claim_token=claim_token,
        claim_expires_at=instant + lease_ttl,
        now=instant,
    )
    return claim_token, acquired, authority_matches


async def prepare_control_action_claim(
    db: AsyncSession,
    request: ControlActionClaimRequest,
) -> ControlActionClaim:
    """Prepare one accepted action inside the caller's acceptance transaction.

    The winner remains uncommitted so requested projections join the receipt,
    writer and lease. The caller must finalize acceptance before any network
    delivery. Losing claims roll back their attempted acceptance.
    """
    instant = request.now or datetime.now(UTC)
    resolved_type = ControlActionType(request.action_type)
    recovery_deadline_at = _resolved_recovery_deadline(
        resolved_type,
        instant,
        request.recovery_timeout_seconds,
        request.recovery_deadline_at,
    )
    reservation = await reserve_control_action(
        db,
        thread_id=request.thread_id,
        action_type=request.action_type,
        idempotency_key=request.idempotency_key,
        request_id=request.request_id,
        payload=request.payload,
        dispatch_id=request.dispatch_id,
        worker_generation=request.worker_generation,
        recovery_deadline_at=recovery_deadline_at,
    )
    action = reservation.action
    if action.dispatch_id is None:
        await db.rollback()
        raise RuntimeError("reserved control action has no stable dispatch id")
    # A rollback expires ORM attributes. Snapshot the protocol-facing values
    # before a losing replay rolls its transaction back, otherwise merely
    # building the replay result attempts implicit async I/O outside greenlet
    # context and raises MissingGreenlet.
    action_id = action.id
    dispatch_id = action.dispatch_id
    applied = action.applied_at is not None
    result_status = action.result_status

    claim_token, acquired, authority_matches = await _claim_reserved_action(
        db, reservation, resolved_type, instant, request.lease_ttl
    )

    if acquired and request.action_type != ControlActionType.CANCEL:
        receipt = await prepare_graph_action_receipt(
            db,
            thread_id=request.thread_id,
            dispatch_id=dispatch_id,
            install_from=request.write_expectation,
        )
        if receipt is None:
            acquired = False
            authority_matches = False
    if not acquired:
        claim_token = None
        await db.rollback()

    return ControlActionClaim(
        action_id=action_id,
        dispatch_id=dispatch_id,
        created=reservation.created,
        payload_matches=reservation.payload_matches,
        acquired=acquired,
        authority_matches=authority_matches,
        applied=applied,
        result_status=result_status,
        claim_token=claim_token,
    )


async def finalize_control_action_acceptance(
    db: AsyncSession,
    claim: ControlActionClaim,
) -> None:
    """Commit the verified claim and all accepted effects before delivery."""
    if not claim.acquired or claim.claim_token is None:
        raise RuntimeError("cannot finalize an unowned control action acceptance")
    await commit_control_action_lease(
        db,
        claim.action_id,
        claim_token=claim.claim_token,
    )


async def _failure_action(
    db: AsyncSession, claim: ControlActionClaim, instant: datetime
) -> tuple[ControlActionModel, str, datetime] | DispatchFailureDisposition:
    action = await db.get(ControlActionModel, claim.action_id, with_for_update=True)
    if action is None or action.dispatch_id != claim.dispatch_id:
        return DispatchFailureDisposition.AUTHORITY_LOST
    if action.applied_at is not None:
        return DispatchFailureDisposition.APPLICATION_WON
    deadline = action.recovery_deadline_at
    if deadline is None or deadline <= instant:
        return DispatchFailureDisposition.DEADLINE_EXPIRED
    token = claim.claim_token
    if token is None or action.claim_token != token:
        return DispatchFailureDisposition.AUTHORITY_LOST
    return action, token, deadline


async def _failure_thread_authority(
    db: AsyncSession, action: ControlActionModel
) -> RunWriteAuthority | DispatchFailureDisposition:
    thread = await db.get(
        ThreadModel,
        action.thread_id,
        with_for_update=True,
        populate_existing=True,
    )
    if thread is None or not thread.is_active:
        return DispatchFailureDisposition.AUTHORITY_LOST
    authority = thread_write_expectation(thread).authority
    if (
        authority.action_type.value != action.action_type
        or authority.action_receipt_id != action.dispatch_id
    ):
        return DispatchFailureDisposition.AUTHORITY_LOST
    return authority


async def record_dispatch_failure(
    db: AsyncSession,
    claim: ControlActionClaim,
    failure_type: FailureType,
    *,
    detail: str | None,
    observed_at: datetime | None = None,
) -> DispatchFailureDisposition:
    """Persist the typed outcome and release only proven non-delivery leases."""
    instant = observed_at or datetime.now(UTC)
    resolved = await _failure_action(db, claim, instant)
    if isinstance(resolved, DispatchFailureDisposition):
        return resolved
    action, claim_token, deadline = resolved
    authority = await _failure_thread_authority(db, action)
    if isinstance(authority, DispatchFailureDisposition):
        return authority

    disposition = DispatchFailureDisposition.AMBIGUOUS_DELIVERY
    if failure_type in _DEFINITE_NON_DELIVERY:
        if not await release_control_action_lease(
            db,
            claim.action_id,
            claim_token=claim_token,
        ):
            return DispatchFailureDisposition.AUTHORITY_LOST
        disposition = DispatchFailureDisposition.DEFINITE_NON_DELIVERY
    await record_recovery_failure(
        db,
        thread_id=action.thread_id,
        authority=authority,
        condition=RecoveryCondition(failure_type.value),
        observed_at=instant,
        next_eligible_at=min(
            instant + timedelta(seconds=2),
            deadline,
        ),
        deadline_at=deadline,
        detail=detail,
    )
    return disposition
