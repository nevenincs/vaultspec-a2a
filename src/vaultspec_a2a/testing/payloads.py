"""Reading a service response a live test just received, and its fields.

A live-service test asserts on a real JSON body, and before it can read anything
it must establish that what came back has the shape the contract promises. These
readers do that once for every tier, under one failure vocabulary.

Every message carries an ``at`` locator naming the response and the path within
it. A service test that reads a wrong-shaped payload fails a long way from the
request that produced it, so a failure without the locator no longer says which
call went wrong.

Two guarantees to know before adding to this module.

``AssertionError``, because that is what these are: an assertion about a payload
a service returned, not a type error in the caller.

VALIDATION, not narrowing. :func:`json_object` and :func:`json_object_list` run
``TypeAdapter.validate_python`` over an untyped decoded payload, which walks the
whole recursive structure. That is a different operation from
:func:`vaultspec_a2a.providers._json_contract.json_object`, which is an
``isinstance`` cast over an ALREADY-typed union - it narrows so the next subscript
typechecks, and validates nothing. The two share a name and an ``at`` convention
and are not interchangeable: ``TypeAdapter(JsonObject)`` rejects ``{"a": object()}``
where both ``TypeAdapter(dict[str, object])`` and the narrowing cast accept it, so
substituting the cast would replace deep validation with a shallow check that no
type checker would report. The readers validate against ``JsonObject`` for that
reason; the looser ``dict[str, object]`` adapter only proves a dict with string
keys.

:func:`json_list` and :func:`json_text` are the exception, and deliberately so:
they are the array and string siblings of that narrowing cast, for a test already
holding a ``JsonValue`` from it. They narrow rather than validate and raise
``TypeError`` exactly as the cast does, so one walk down a provider response keeps
one failure posture from its first step to its last.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ..providers import JsonObject
from ..utils.coercion import coerce_string_list

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..providers import JsonValue

__all__ = [
    "json_list",
    "json_object",
    "json_object_list",
    "json_text",
    "required_bool",
    "required_text",
    "text_list",
]

_JSON_OBJECT: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)
_JSON_OBJECT_LIST: Final[TypeAdapter[list[JsonObject]]] = TypeAdapter(list[JsonObject])


def json_object(value: object, *, at: str) -> JsonObject:
    """Validate one decoded service payload as a JSON object."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"expected a JSON object at {at}: {exc}") from exc


def json_object_list(value: object, *, at: str) -> list[JsonObject]:
    """Validate one decoded service payload as a list of JSON objects."""
    try:
        return _JSON_OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"expected a JSON object list at {at}: {exc}") from exc


def text_list(value: object, *, at: str) -> list[str]:
    """Validate one decoded service payload as a list of strings.

    Strict, so a number or a boolean is refused rather than coerced to its text:
    a payload that carried one has already broken its contract.
    """
    texts = coerce_string_list(value)
    if texts is None:
        raise AssertionError(f"expected a text list at {at}: {value!r}")
    return texts


def required_text(body: Mapping[str, object], field: str, *, at: str) -> str:
    """Read one required text field from a validated service payload.

    ``Mapping`` rather than ``dict``: ``dict`` is invariant, so a ``dict`` value
    type would refuse the ``JsonObject`` that :func:`json_object` returns, while
    ``Mapping`` is covariant in its value type and accepts both.
    """
    value = body.get(field)
    if not isinstance(value, str):
        raise AssertionError(f"{at}.{field} was not text: {value!r}")
    return value


def required_bool(body: Mapping[str, object], field: str, *, at: str) -> bool:
    """Read one required boolean field from a validated service payload."""
    value = body.get(field)
    if not isinstance(value, bool):
        raise AssertionError(f"{at}.{field} was not boolean: {value!r}")
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
