"""Typed component records and legacy argument binder for desktop discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping


_MISSING_DESKTOP_RECORD_FIELD = object()
_DESKTOP_RECORD_FIELDS = (
    "version",
    "profile",
    "generation",
    "protocol_min",
    "protocol_max",
    "pid",
    "start_fingerprint",
    "host",
    "port",
    "last_heartbeat",
    "owner",
    "credential_reference",
)
_DESKTOP_RECORD_DEFAULTS = (_MISSING_DESKTOP_RECORD_FIELD,) * len(
    _DESKTOP_RECORD_FIELDS
)


def bind_desktop_record_fields(
    args: tuple[object, ...],
    options: Mapping[str, object],
) -> tuple[object, ...]:
    """Bind the original public field order for desktop-record construction."""
    if len(args) > len(_DESKTOP_RECORD_FIELDS):
        raise TypeError(
            "expected at most "
            f"{len(_DESKTOP_RECORD_FIELDS)} positional arguments, "
            f"got {len(args)}"
        )
    unknown = next(
        (name for name in options if name not in _DESKTOP_RECORD_FIELDS),
        None,
    )
    if unknown is not None:
        raise TypeError(f"unexpected keyword argument {unknown!r}")
    duplicate = next(
        (name for name in _DESKTOP_RECORD_FIELDS[: len(args)] if name in options),
        None,
    )
    if duplicate is not None:
        raise TypeError(f"multiple values for argument {duplicate!r}")
    return tuple(
        args[index]
        if index < len(args)
        else options.get(name, _DESKTOP_RECORD_DEFAULTS[index])
        for index, name in enumerate(_DESKTOP_RECORD_FIELDS)
    )


def required_desktop_record_field(name: str, value: object) -> object:
    if value is _MISSING_DESKTOP_RECORD_FIELD:
        raise TypeError(f"missing required argument {name!r}")
    return value


@dataclass(frozen=True, slots=True)
class DesktopRecordIdentity:
    """Record and resident identity fields."""

    version: int
    profile: str
    generation: str
    owner: str


@dataclass(frozen=True, slots=True)
class DesktopRecordProtocol:
    """Control protocol range advertised by the resident."""

    protocol_min: int
    protocol_max: int


@dataclass(frozen=True, slots=True)
class DesktopRecordProcess:
    """Process identity used to validate the resident."""

    pid: int
    start_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class DesktopRecordEndpoint:
    """Loopback endpoint advertised by the resident."""

    host: str
    port: int


@dataclass(frozen=True, slots=True)
class DesktopRecordState:
    """Freshness and credential-reference state for the resident."""

    last_heartbeat: int
    credential_reference: str | None


class DesktopDiscoveryRecordOptions(TypedDict, total=False):
    version: int
    profile: str
    generation: str
    protocol_min: int
    protocol_max: int
    pid: int
    start_fingerprint: str | None
    host: str
    port: int
    last_heartbeat: int
    owner: str
    credential_reference: str | None
