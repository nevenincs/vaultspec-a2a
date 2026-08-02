"""Normalized provider-owned model catalog and selection contracts.

The types contain safe display metadata and opaque values reported by a
provider lane. They define no product model names, cross-provider tiers,
credentials, or invocation defaults.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from time import monotonic
from typing import Final

__all__ = [
    "AdmissionState",
    "AuthenticationState",
    "CacheFreshness",
    "CatalogCacheCapacityError",
    "CatalogCacheSnapshot",
    "CatalogRefreshCache",
    "CatalogRefreshInvalidatedError",
    "CatalogState",
    "CatalogStatus",
    "ControlKind",
    "ControlSelection",
    "HealthState",
    "ModelCatalogEntry",
    "NativeControl",
    "NativeControlOption",
    "ProviderCatalog",
    "ProviderCatalogKey",
    "ProviderRecord",
    "SelectionReference",
    "StructuredProviderHealth",
]

CATALOG_SCHEMA_VERSION: Final = 1
SELECTION_SCHEMA_VERSION: Final = 1
MAX_TEXT_LENGTH: Final = 1_024
MAX_DISPLAY_LENGTH: Final = 256
MAX_MODELS: Final = 256
MAX_CONTROLS: Final = 32
MAX_OPTIONS: Final = 128
MAX_CAPABILITIES: Final = 64
MAX_HEALTH_REASONS: Final = 16


def _required_text(
    value: str, field_name: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and already normalized")
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds the {max_length}-character limit")
    return value


def _optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _required_text(value, field_name)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _unique(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


class HealthState(StrEnum):
    """A factual binary health axis whose evidence may still be unknown."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class AuthenticationState(StrEnum):
    """Authentication evidence, separate from configuration presence."""

    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class AdmissionState(StrEnum):
    """Completed-turn admission evidence for an execution lane."""

    ADMITTED = "admitted"
    NOT_ADMITTED = "not_admitted"
    UNKNOWN = "unknown"


class CatalogStatus(StrEnum):
    """Provider catalog availability and freshness."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    UNKNOWN = "unknown"


class CacheFreshness(StrEnum):
    """Whether a cached catalog remains inside its local TTL."""

    FRESH = "fresh"
    STALE = "stale"


class ControlKind(StrEnum):
    """Provider-native control category without cross-provider semantics."""

    MODEL_CONFIG = "model_config"
    THOUGHT_LEVEL = "thought_level"
    SERVICE_TIER = "service_tier"
    OTHER = "other"


class CatalogRefreshInvalidatedError(RuntimeError):
    """A refresh result was fenced because its lane changed during discovery."""


class CatalogCacheCapacityError(RuntimeError):
    """The bounded cache has no expired inactive lane available for eviction."""


@dataclass(frozen=True, slots=True)
class NativeControlOption:
    """One provider-issued value for a provider-native control."""

    option_id: str
    provider_value: str
    display_name: str
    description: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.option_id, "option_id")
        _required_text(self.provider_value, "provider_value")
        _required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
        _optional_text(self.description, "description")


@dataclass(frozen=True, slots=True)
class NativeControl:
    """An ordered provider-native selector and its opaque choices."""

    control_id: str
    kind: ControlKind
    display_name: str
    options: tuple[NativeControlOption, ...]
    default_option_id: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))
        _required_text(self.control_id, "control_id")
        _required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
        if len(self.options) > MAX_OPTIONS:
            raise ValueError(
                f"native control options exceed the {MAX_OPTIONS}-item limit"
            )
        option_ids = tuple(option.option_id for option in self.options)
        _unique(option_ids, "native control option ids")
        if self.default_option_id is not None:
            _required_text(self.default_option_id, "default_option_id")
            if self.default_option_id not in option_ids:
                raise ValueError("default_option_id must name an advertised option")
        _optional_text(self.description, "description")


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """A server-local entry wrapping one provider-issued model value."""

    entry_id: str
    provider_value: str
    display_name: str
    description: str | None = None
    capabilities: tuple[str, ...] = ()
    native_control_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "native_control_ids", tuple(self.native_control_ids))
        _required_text(self.entry_id, "entry_id")
        _required_text(self.provider_value, "provider_value")
        _required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
        if len(self.capabilities) > MAX_CAPABILITIES:
            raise ValueError(f"capabilities exceed the {MAX_CAPABILITIES}-item limit")
        for capability in self.capabilities:
            _required_text(capability, "capability")
        _unique(self.capabilities, "capabilities")
        if len(self.native_control_ids) > MAX_CONTROLS:
            raise ValueError(
                f"model native control ids exceed the {MAX_CONTROLS}-item limit"
            )
        for control_id in self.native_control_ids:
            _required_text(control_id, "model native control id")
        _unique(self.native_control_ids, "model native control ids")
        _optional_text(self.description, "description")


@dataclass(frozen=True, slots=True)
class CatalogState:
    """Provider-supplied catalog revision and freshness evidence."""

    status: CatalogStatus
    checked_at: datetime
    revision: str | None = None
    expires_at: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", _utc(self.checked_at, "checked_at"))
        if self.revision is not None:
            _required_text(self.revision, "revision")
        _optional_text(self.reason, "catalog reason")
        if self.expires_at is not None:
            expires_at = _utc(self.expires_at, "expires_at")
            object.__setattr__(self, "expires_at", expires_at)
            if expires_at < self.checked_at:
                raise ValueError("expires_at must not precede checked_at")
        if self.status in {CatalogStatus.AVAILABLE, CatalogStatus.STALE} and (
            self.revision is None
        ):
            raise ValueError("an available or stale catalog requires a revision")


@dataclass(frozen=True, slots=True)
class StructuredProviderHealth:
    """Independent provider health facts and their derived selectability."""

    configured: HealthState
    transport: HealthState
    authentication: AuthenticationState
    catalog: CatalogStatus
    admission: AdmissionState
    selectable: bool
    reasons: tuple[str, ...]
    checked_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "checked_at", _utc(self.checked_at, "checked_at"))
        if len(self.reasons) > MAX_HEALTH_REASONS:
            raise ValueError(
                f"health reasons exceed the {MAX_HEALTH_REASONS}-item limit"
            )
        for reason in self.reasons:
            _required_text(reason, "health reason")
        _unique(self.reasons, "health reasons")
        expected = (
            self.configured is HealthState.AVAILABLE
            and self.transport is HealthState.AVAILABLE
            and self.authentication
            in {AuthenticationState.AUTHENTICATED, AuthenticationState.NOT_APPLICABLE}
            and self.catalog is CatalogStatus.AVAILABLE
            and self.admission is AdmissionState.ADMITTED
        )
        if self.selectable is not expected:
            raise ValueError("selectable must be derived from all health axes")

    @classmethod
    def derive(
        cls,
        *,
        configured: HealthState,
        transport: HealthState,
        authentication: AuthenticationState,
        catalog: CatalogStatus,
        admission: AdmissionState,
        reasons: tuple[str, ...] = (),
        checked_at: datetime,
    ) -> StructuredProviderHealth:
        """Build health with selectability derived from every required axis."""
        selectable = (
            configured is HealthState.AVAILABLE
            and transport is HealthState.AVAILABLE
            and authentication
            in {AuthenticationState.AUTHENTICATED, AuthenticationState.NOT_APPLICABLE}
            and catalog is CatalogStatus.AVAILABLE
            and admission is AdmissionState.ADMITTED
        )
        return cls(
            configured=configured,
            transport=transport,
            authentication=authentication,
            catalog=catalog,
            admission=admission,
            selectable=selectable,
            reasons=reasons,
            checked_at=checked_at,
        )


@dataclass(frozen=True, slots=True)
class ProviderCatalogKey:
    """Identity of one execution-mode-specific provider lane."""

    provider_id: str
    execution_mode: str

    def __post_init__(self) -> None:
        _required_text(self.provider_id, "provider_id")
        _required_text(self.execution_mode, "execution_mode")


@dataclass(frozen=True, slots=True)
class ProviderCatalog:
    """Immutable normalized choices advertised by one provider lane."""

    key: ProviderCatalogKey
    state: CatalogState
    models: tuple[ModelCatalogEntry, ...]
    native_controls: tuple[NativeControl, ...] = ()
    schema_version: int = CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", tuple(self.models))
        object.__setattr__(self, "native_controls", tuple(self.native_controls))
        if self.schema_version != CATALOG_SCHEMA_VERSION:
            raise ValueError("unsupported catalog schema_version")
        if len(self.models) > MAX_MODELS:
            raise ValueError(f"models exceed the {MAX_MODELS}-item limit")
        if len(self.native_controls) > MAX_CONTROLS:
            raise ValueError(f"native controls exceed the {MAX_CONTROLS}-item limit")
        _unique(tuple(model.entry_id for model in self.models), "model entry ids")
        _unique(
            tuple(control.control_id for control in self.native_controls),
            "native control ids",
        )
        known_control_ids = {control.control_id for control in self.native_controls}
        for model in self.models:
            unknown = set(model.native_control_ids) - known_control_ids
            if unknown:
                raise ValueError(
                    "model native_control_ids must name advertised controls"
                )
        if self.state.status in {CatalogStatus.UNAVAILABLE, CatalogStatus.UNKNOWN} and (
            self.models
        ):
            raise ValueError("an unavailable catalog cannot advertise models")

    def model(self, entry_id: str) -> ModelCatalogEntry | None:
        """Return the model with ``entry_id`` without interpreting its value."""
        return next(
            (model for model in self.models if model.entry_id == entry_id), None
        )


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """Provider display metadata, health, and execution-lane catalog."""

    provider_id: str
    display_name: str
    execution_mode: str
    health: StructuredProviderHealth
    catalog: ProviderCatalog

    def __post_init__(self) -> None:
        _required_text(self.provider_id, "provider_id")
        _required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
        _required_text(self.execution_mode, "execution_mode")
        if self.catalog.key != ProviderCatalogKey(
            provider_id=self.provider_id, execution_mode=self.execution_mode
        ):
            raise ValueError("provider record and catalog lane identities must match")


@dataclass(frozen=True, slots=True)
class ControlSelection:
    """One bounded selection of an advertised provider-native option."""

    control_id: str
    option_id: str

    def __post_init__(self) -> None:
        _required_text(self.control_id, "control_id")
        _required_text(self.option_id, "option_id")


@dataclass(frozen=True, slots=True)
class SelectionReference:
    """A replay-safe reference to a served catalog entry and native controls."""

    provider_id: str
    execution_mode: str
    catalog_revision: str
    entry_id: str
    controls: tuple[ControlSelection, ...] = ()
    schema_version: int = SELECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "controls", tuple(self.controls))
        _required_text(self.provider_id, "provider_id")
        _required_text(self.execution_mode, "execution_mode")
        _required_text(self.catalog_revision, "catalog_revision")
        _required_text(self.entry_id, "entry_id")
        if self.schema_version != SELECTION_SCHEMA_VERSION:
            raise ValueError("unsupported selection schema_version")
        if len(self.controls) > MAX_CONTROLS:
            raise ValueError(f"selected controls exceed the {MAX_CONTROLS}-item limit")
        _unique(
            tuple(selection.control_id for selection in self.controls),
            "selected control ids",
        )

    def fingerprint(self) -> str:
        """Return a canonical digest for same-id replay comparison."""
        payload = {
            "catalog_revision": self.catalog_revision,
            "controls": [
                {"control_id": item.control_id, "option_id": item.option_id}
                for item in sorted(self.controls, key=lambda item: item.control_id)
            ],
            "entry_id": self.entry_id,
            "execution_mode": self.execution_mode,
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CatalogCacheSnapshot:
    """A catalog plus local refresh-cache timing state."""

    catalog: ProviderCatalog
    refreshed_at: datetime
    expires_at: datetime
    freshness: CacheFreshness


@dataclass(frozen=True, slots=True)
class _StoredCatalog:
    catalog: ProviderCatalog
    refreshed_at: datetime
    expires_at: datetime
    deadline: float


@dataclass(slots=True)
class _LaneLock:
    lock: asyncio.Lock
    users: int = 0


CatalogLoader = Callable[[ProviderCatalogKey], Awaitable[ProviderCatalog]]


class CatalogRefreshCache:
    """Concurrency-safe, per-lane single-flight TTL cache for catalog discovery."""

    def __init__(self, ttl: timedelta, *, max_lanes: int = 128) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        if max_lanes <= 0:
            raise ValueError("max_lanes must be positive")
        self._ttl = ttl
        self._max_lanes = max_lanes
        self._entries: dict[ProviderCatalogKey, _StoredCatalog] = {}
        self._locks: dict[ProviderCatalogKey, _LaneLock] = {}
        self._generations: dict[ProviderCatalogKey, int] = {}
        self._index_lock = asyncio.Lock()

    async def _lock_for(self, key: ProviderCatalogKey) -> _LaneLock:
        async with self._index_lock:
            lane = self._locks.setdefault(key, _LaneLock(asyncio.Lock()))
            lane.users += 1
            return lane

    async def _release_lock(self, key: ProviderCatalogKey, lane: _LaneLock) -> None:
        async with self._index_lock:
            lane.users -= 1
            if lane.users == 0 and key not in self._entries:
                self._locks.pop(key, None)
                self._generations.pop(key, None)

    def _make_capacity(self, key: ProviderCatalogKey, now: float) -> None:
        if key in self._entries or len(self._entries) < self._max_lanes:
            return
        candidates: list[tuple[float, ProviderCatalogKey]] = []
        for lane_key, entry in self._entries.items():
            lane = self._locks.get(lane_key)
            if entry.deadline <= now and (lane is None or lane.users == 0):
                candidates.append((entry.deadline, lane_key))
        if not candidates:
            raise CatalogCacheCapacityError(
                "catalog cache capacity reached with no expired inactive lane"
            )
        _, evicted = min(candidates, key=lambda item: item[0])
        self._entries.pop(evicted, None)
        self._locks.pop(evicted, None)
        self._generations.pop(evicted, None)

    @staticmethod
    def _snapshot(entry: _StoredCatalog, now: float) -> CatalogCacheSnapshot:
        freshness = (
            CacheFreshness.FRESH if now < entry.deadline else CacheFreshness.STALE
        )
        return CatalogCacheSnapshot(
            catalog=entry.catalog,
            refreshed_at=entry.refreshed_at,
            expires_at=entry.expires_at,
            freshness=freshness,
        )

    def peek(self, key: ProviderCatalogKey) -> CatalogCacheSnapshot | None:
        """Return the snapshot, including stale data, without refreshing."""
        entry = self._entries.get(key)
        return None if entry is None else self._snapshot(entry, monotonic())

    async def get(
        self,
        key: ProviderCatalogKey,
        loader: CatalogLoader,
        *,
        force_refresh: bool = False,
    ) -> CatalogCacheSnapshot:
        """Return a fresh snapshot, coalescing concurrent refreshes per lane."""
        now = monotonic()
        current = self._entries.get(key)
        observed = current
        if not force_refresh and current is not None and now < current.deadline:
            return self._snapshot(current, now)

        lane = await self._lock_for(key)
        try:
            async with lane.lock:
                now = monotonic()
                current = self._entries.get(key)
                if not force_refresh and current is not None and now < current.deadline:
                    return self._snapshot(current, now)
                if force_refresh and current is not None and current is not observed:
                    return self._snapshot(current, now)

                generation = self._generations.get(key, 0)
                catalog = await loader(key)
                if catalog.key != key:
                    raise ValueError(
                        "catalog loader returned a different provider lane"
                    )
                refreshed_at = datetime.now(UTC)
                expires_at = refreshed_at + self._ttl
                if catalog.state.expires_at is not None:
                    expires_at = min(expires_at, catalog.state.expires_at)
                if catalog.state.status is CatalogStatus.STALE:
                    expires_at = refreshed_at
                lifetime = max(0.0, (expires_at - refreshed_at).total_seconds())
                stored = _StoredCatalog(
                    catalog=catalog,
                    refreshed_at=refreshed_at,
                    expires_at=expires_at,
                    deadline=monotonic() + lifetime,
                )
                async with self._index_lock:
                    if self._generations.get(key, 0) != generation:
                        raise CatalogRefreshInvalidatedError(
                            "catalog lane was invalidated during refresh"
                        )
                    self._make_capacity(key, monotonic())
                    self._entries[key] = stored
                return self._snapshot(stored, monotonic())
        finally:
            await self._release_lock(key, lane)

    def invalidate(self, key: ProviderCatalogKey) -> None:
        """Expire one lane without discarding its visible stale snapshot."""
        if key not in self._entries and key not in self._locks:
            return
        self._generations[key] = self._generations.get(key, 0) + 1
        current = self._entries.get(key)
        if current is not None:
            self._entries[key] = _StoredCatalog(
                catalog=current.catalog,
                refreshed_at=current.refreshed_at,
                expires_at=current.expires_at,
                deadline=float("-inf"),
            )
