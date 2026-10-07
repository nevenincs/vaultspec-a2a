"""Closed JSON values used at provider protocol boundaries.

The provider layer emits protocol/configuration objects rather than arbitrary
Python containers.  Keeping the recursive shape here lets each boundary prove
its payload is serialisable, while ``freeze_json`` protects closed registries.
"""

from __future__ import annotations

from types import MappingProxyType

__all__ = [
    "FrozenJsonObject",
    "FrozenJsonValue",
    "JsonObject",
    "JsonValue",
    "freeze_json",
    "lenient_json_object",
    "lenient_json_object_list",
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


# ---------------------------------------------------------------------------
# Narrowing readers
#
# ``JsonValue`` is recursive, so one step into a payload - ``body["thread"]`` -
# yields the whole union and the NEXT step is unsubscriptable. Describing the
# shape honestly and navigating it are in tension, and the tension resolves at
# the reader rather than by widening the type back to ``Any``: a consumer that
# knows it is holding an object says so, once, and gets a typed value.
# ---------------------------------------------------------------------------


def lenient_json_object(value: JsonValue | None) -> JsonObject:
    """Return an object payload, or the empty object for anything malformed.

    These readers take UNTRUSTED provider output, where a malformed field is an
    ordinary event that must degrade to an empty value rather than abort a live
    turn.
    """
    return value if isinstance(value, dict) else {}


def lenient_json_object_list(value: JsonValue | None) -> list[JsonObject]:
    """Return only the object entries of an untrusted JSON array.

    Non-object entries are dropped rather than refused, for the same reason
    :func:`lenient_json_object` degrades: a provider may interleave shapes this
    caller does not model, and one unexpected entry must not cost the rest.
    """
    return (
        [entry for entry in value if isinstance(entry, dict)]
        if isinstance(value, list)
        else []
    )
