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
    "json_list",
    "json_object",
    "json_text",
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


# ---------------------------------------------------------------------------
# Narrowing readers
#
# ``JsonValue`` is recursive, so one step into a payload - ``body["thread"]`` -
# yields the whole union and the NEXT step is unsubscriptable. Describing the
# shape honestly and navigating it are in tension, and the tension resolves at
# the reader rather than by widening the type back to ``Any``: a consumer that
# knows it is holding an object says so, once, and gets a typed value plus a
# loud failure when the payload disagrees.
#
# These raise rather than return a default deliberately. A caller reaching two
# levels into a protocol response has an expectation about its shape; if that is
# wrong, saying which key held what beats an empty dict flowing onward to fail
# somewhere less informative.
# ---------------------------------------------------------------------------


def json_object(value: JsonValue, *, at: str = "value") -> JsonObject:
    """Return *value* as a JSON object, or raise naming what it actually was."""
    if not isinstance(value, dict):
        msg = f"expected a JSON object at {at}, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def json_list(value: JsonValue, *, at: str = "value") -> list[JsonValue]:
    """Return *value* as a JSON array, or raise naming what it actually was."""
    if not isinstance(value, list):
        msg = f"expected a JSON array at {at}, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def json_text(value: JsonValue, *, at: str = "value") -> str:
    """Return *value* as a JSON string, or raise naming what it actually was."""
    if not isinstance(value, str):
        msg = f"expected a JSON string at {at}, got {type(value).__name__}"
        raise TypeError(msg)
    return value
