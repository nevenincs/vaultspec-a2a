"""Normalized provider-owned model catalog and selection contracts.

The types contain safe display metadata and opaque values reported by a
provider lane. They define no product model names, cross-provider tiers,
credentials, or invocation defaults.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, TypedDict, Unpack, cast

from ._provider_catalog_cache import (
    CatalogCacheSnapshot as CatalogCacheSnapshot,
)
from ._provider_catalog_cache import CatalogRefreshCacheBase


class CacheFreshness(StrEnum):
    """Whether a cached catalog remains inside its local TTL."""

    FRESH = "fresh"
    STALE = "stale"


class CatalogRefreshInvalidatedError(RuntimeError):
    """A refresh result was fenced because its lane changed during discovery."""


class CatalogCacheCapacityError(RuntimeError):
    """The bounded cache has no expired inactive lane available for eviction."""


class CatalogRefreshSuppressedError(RuntimeError):
    """A lane's discovery was skipped because its last attempt recently failed.

    Raised INSTEAD of running the loader, so a caller sees the same failure shape
    it would have seen from the real attempt without paying that attempt's cost
    again. ``failure_type`` is the class name of the exception the real attempt
    raised - a type name, never a provider message, which can carry credentials,
    URLs, or local paths.
    """

    def __init__(self, failure_type: str, retry_after_seconds: float) -> None:
        super().__init__(
            f"provider catalog discovery is suppressed after a {failure_type}; "
            f"retrying in {retry_after_seconds:.1f}s"
        )
        self.failure_type = failure_type
        self.retry_after_seconds = retry_after_seconds


__all__ = [
    "AdmissionState",
    "AuthenticationState",
    "CacheFreshness",
    "CatalogRefreshCache",
    "CatalogRefreshInvalidatedError",
    "CatalogRefreshSuppressedError",
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
    "ProviderHealthAxes",
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


def required_text(
    value: str, field_name: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str:
    """Return *value* as a non-blank, already-normalized, bounded string, or raise.

    Public so every catalog dataclass shares one invariant: a plain
    ``ValueError`` naming the field, not a lane's own protocol-error dialect.
    The optional ``max_length`` override keeps display fields bounded more
    tightly than identifiers and reasons.
    """
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and already normalized")
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds the {max_length}-character limit")
    return value


def _optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        required_text(value, field_name)


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


class ControlKind(StrEnum):
    """Provider-native control category without cross-provider semantics."""

    MODEL_CONFIG = "model_config"
    THOUGHT_LEVEL = "thought_level"
    SERVICE_TIER = "service_tier"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class NativeControlOption:
    """One provider-issued value for a provider-native control."""

    option_id: str
    provider_value: str
    display_name: str
    description: str | None = None

    def __post_init__(self) -> None:
        required_text(self.option_id, "option_id")
        required_text(self.provider_value, "provider_value")
        required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
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
        required_text(self.control_id, "control_id")
        required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
        if len(self.options) > MAX_OPTIONS:
            raise ValueError(
                f"native control options exceed the {MAX_OPTIONS}-item limit"
            )
        option_ids = tuple(option.option_id for option in self.options)
        _unique(option_ids, "native control option ids")
        if self.default_option_id is not None:
            required_text(self.default_option_id, "default_option_id")
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
        required_text(self.entry_id, "entry_id")
        required_text(self.provider_value, "provider_value")
        required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
        if len(self.capabilities) > MAX_CAPABILITIES:
            raise ValueError(f"capabilities exceed the {MAX_CAPABILITIES}-item limit")
        for capability in self.capabilities:
            required_text(capability, "capability")
        _unique(self.capabilities, "capabilities")
        if len(self.native_control_ids) > MAX_CONTROLS:
            raise ValueError(
                f"model native control ids exceed the {MAX_CONTROLS}-item limit"
            )
        for control_id in self.native_control_ids:
            required_text(control_id, "model native control id")
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
            required_text(self.revision, "revision")
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
class ProviderHealthAxes:
    """Independent provider health observations before selectability is derived."""

    configured: HealthState
    transport: HealthState
    authentication: AuthenticationState
    catalog: CatalogStatus
    admission: AdmissionState


class _StructuredProviderHealthOptions(TypedDict, total=False):
    configured: HealthState
    transport: HealthState
    authentication: AuthenticationState
    catalog: CatalogStatus
    admission: AdmissionState
    selectable: bool
    reasons: tuple[str, ...]
    checked_at: datetime


_STRUCTURED_PROVIDER_HEALTH_FIELDS = (
    "configured",
    "transport",
    "authentication",
    "catalog",
    "admission",
    "selectable",
    "reasons",
    "checked_at",
)
_STRUCTURED_PROVIDER_HEALTH_MISSING = object()


def _bind_structured_provider_health_fields(
    args: tuple[object, ...], options: _StructuredProviderHealthOptions
) -> tuple[object, ...]:
    """Bind the legacy health fields before grouping the five axes."""
    field_names = _STRUCTURED_PROVIDER_HEALTH_FIELDS
    if len(args) > len(field_names):
        raise TypeError(
            f"expected at most {len(field_names)} positional arguments, got {len(args)}"
        )
    unknown = next((name for name in options if name not in field_names), None)
    if unknown is not None:
        raise TypeError(f"unexpected keyword argument {unknown!r}")
    duplicate = next(
        (name for name in field_names[: len(args)] if name in options),
        None,
    )
    if duplicate is not None:
        raise TypeError(f"multiple values for argument {duplicate!r}")
    return tuple(
        args[index]
        if index < len(args)
        else options.get(name, _STRUCTURED_PROVIDER_HEALTH_MISSING)
        for index, name in enumerate(field_names)
    )


def _required_health_field(name: str, value: object) -> object:
    if value is _STRUCTURED_PROVIDER_HEALTH_MISSING:
        raise TypeError(f"missing required argument {name!r}")
    return value


@dataclass(frozen=True, slots=True)
class StructuredProviderHealth:
    """Independent provider health facts and their derived selectability."""

    _axes: ProviderHealthAxes
    selectable: bool
    reasons: tuple[str, ...]
    checked_at: datetime

    def __init__(
        self,
        *args: object,
        **options: Unpack[_StructuredProviderHealthOptions],
    ) -> None:
        values = _bind_structured_provider_health_fields(args, options)
        object.__setattr__(
            self,
            "_axes",
            ProviderHealthAxes(
                configured=cast(
                    "HealthState", _required_health_field("configured", values[0])
                ),
                transport=cast(
                    "HealthState", _required_health_field("transport", values[1])
                ),
                authentication=cast(
                    "AuthenticationState",
                    _required_health_field("authentication", values[2]),
                ),
                catalog=cast(
                    "CatalogStatus", _required_health_field("catalog", values[3])
                ),
                admission=cast(
                    "AdmissionState", _required_health_field("admission", values[4])
                ),
            ),
        )
        object.__setattr__(
            self,
            "selectable",
            cast("bool", _required_health_field("selectable", values[5])),
        )
        object.__setattr__(
            self,
            "reasons",
            cast("tuple[str, ...]", _required_health_field("reasons", values[6])),
        )
        object.__setattr__(
            self,
            "checked_at",
            cast("datetime", _required_health_field("checked_at", values[7])),
        )
        self.__post_init__()

    @property
    def configured(self) -> HealthState:
        return self._axes.configured

    @property
    def transport(self) -> HealthState:
        return self._axes.transport

    @property
    def authentication(self) -> AuthenticationState:
        return self._axes.authentication

    @property
    def catalog(self) -> CatalogStatus:
        return self._axes.catalog

    @property
    def admission(self) -> AdmissionState:
        return self._axes.admission

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "checked_at", _utc(self.checked_at, "checked_at"))
        if len(self.reasons) > MAX_HEALTH_REASONS:
            raise ValueError(
                f"health reasons exceed the {MAX_HEALTH_REASONS}-item limit"
            )
        for reason in self.reasons:
            required_text(reason, "health reason")
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
        axes: ProviderHealthAxes,
        *,
        reasons: tuple[str, ...] = (),
        checked_at: datetime,
    ) -> StructuredProviderHealth:
        """Build health with selectability derived from every required axis."""
        selectable = (
            axes.configured is HealthState.AVAILABLE
            and axes.transport is HealthState.AVAILABLE
            and axes.authentication
            in {AuthenticationState.AUTHENTICATED, AuthenticationState.NOT_APPLICABLE}
            and axes.catalog is CatalogStatus.AVAILABLE
            and axes.admission is AdmissionState.ADMITTED
        )
        return cls(
            configured=axes.configured,
            transport=axes.transport,
            authentication=axes.authentication,
            catalog=axes.catalog,
            admission=axes.admission,
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
        required_text(self.provider_id, "provider_id")
        required_text(self.execution_mode, "execution_mode")


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
        _validate_model_controls(self.models, self.native_controls)
        if self.state.status in {CatalogStatus.UNAVAILABLE, CatalogStatus.UNKNOWN} and (
            self.models
        ):
            raise ValueError("an unavailable catalog cannot advertise models")

    def model(self, entry_id: str) -> ModelCatalogEntry | None:
        """Return the model with ``entry_id`` without interpreting its value."""
        return next(
            (model for model in self.models if model.entry_id == entry_id), None
        )


def _validate_model_controls(
    models: tuple[ModelCatalogEntry, ...], controls: tuple[NativeControl, ...]
) -> None:
    known_control_ids = {control.control_id for control in controls}
    for model in models:
        unknown = set(model.native_control_ids) - known_control_ids
        if unknown:
            raise ValueError("model native_control_ids must name advertised controls")


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """Provider display metadata, health, and execution-lane catalog."""

    provider_id: str
    display_name: str
    execution_mode: str
    health: StructuredProviderHealth
    catalog: ProviderCatalog

    def __post_init__(self) -> None:
        required_text(self.provider_id, "provider_id")
        required_text(self.display_name, "display_name", max_length=MAX_DISPLAY_LENGTH)
        required_text(self.execution_mode, "execution_mode")
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
        required_text(self.control_id, "control_id")
        required_text(self.option_id, "option_id")


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
        required_text(self.provider_id, "provider_id")
        required_text(self.execution_mode, "execution_mode")
        required_text(self.catalog_revision, "catalog_revision")
        required_text(self.entry_id, "entry_id")
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


class CatalogRefreshCache(CatalogRefreshCacheBase):
    """Public refresh cache with its declared catalog-module identity."""
