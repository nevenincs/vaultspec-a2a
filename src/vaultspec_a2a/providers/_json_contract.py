"""Closed JSON values used at provider protocol boundaries.

The provider layer emits protocol/configuration objects rather than arbitrary
Python containers.  Keeping the recursive shape here lets each boundary prove
its payload is serialisable, while ``freeze_json`` protects closed registries
and ``thaw_json`` gives every consumer an independent mutable wire object.
"""

from __future__ import annotations

from types import MappingProxyType

__all__ = [
    "FrozenJsonObject",
    "FrozenJsonValue",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "freeze_json",
    "thaw_json",
]

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

type FrozenJsonScalar = JsonScalar
type FrozenJsonValue = (
    FrozenJsonScalar
    | tuple[FrozenJsonValue, ...]
    | MappingProxyType[str, FrozenJsonValue]
)
type FrozenJsonObject = MappingProxyType[str, FrozenJsonValue]


def freeze_json(value: JsonValue) -> FrozenJsonValue:
    """Recursively freeze one JSON-shaped value without changing its data."""
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, dict):
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    return value


def thaw_json(value: FrozenJsonValue) -> JsonValue:
    """Return a fresh mutable JSON-shaped counterpart of one frozen value."""
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    if isinstance(value, MappingProxyType):
        return {key: thaw_json(item) for key, item in value.items()}
    return value
