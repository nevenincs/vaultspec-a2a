"""Reading a service response a live test just received, and its fields.

A live-service test asserts on a real JSON body, and before it can read anything
it must establish that what came back has the shape the contract promises. Nine
service suites had each written that out for themselves, so the same four readers
existed nine times over with three different failure vocabularies between them.

The failure text is why these are worth sharing rather than inlining. A service
test that reads a wrong-shaped payload fails a long way from the request that
produced it, so every message carries an ``at`` locator naming the response and
the path within it. Independent copies of that convention drift, and a drifted
locator is a test whose failure no longer says which call went wrong.

Two decisions worth knowing before adding to this module.

``AssertionError``, because that is what these are: an assertion about a payload
a service returned, not a type error in the caller. The suite that self-tests its
readers already asserted exactly that, so converging kept its coverage intact
rather than requiring it to be rewritten.

VALIDATION, not narrowing, and this is the distinction that matters most. These
run ``TypeAdapter.validate_python`` over an untyped decoded payload, which walks
the whole recursive structure. That is a different operation from
:func:`vaultspec_a2a.providers._json_contract.json_object`, which is an
``isinstance`` cast over an ALREADY-typed union - it narrows so the next subscript
typechecks, and validates nothing. The two share a name and an ``at`` convention
and are not interchangeable: routing these callers through that one would replace
deep validation with a shallow cast, and no type checker would report it. Proven
rather than assumed - ``TypeAdapter(JsonObject)`` rejects ``{"a": object()}``
where both ``TypeAdapter(dict[str, object])`` and the narrowing cast accept it.

That same proof is why the readers here validate against ``JsonObject`` rather
than the looser ``dict[str, object]`` several callers used: the loose adapter only
ever proved "a dict with string keys", which is what the narrowing cast already
does. For a payload decoded from real JSON the tightening is a no-op in practice,
but it IS a tightening and is declared as one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ..providers._json_contract import JsonObject

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "json_object",
    "json_object_list",
    "required_bool",
    "required_text",
]

_JSON_OBJECT: Final = TypeAdapter(JsonObject)
_JSON_OBJECT_LIST: Final = TypeAdapter(list[JsonObject])


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
