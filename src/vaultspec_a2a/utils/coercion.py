"""Strict coercion of untrusted JSON-shaped values.

Records arriving from a file, a peer service, or an event stream are parsed
JSON, so a field typed as an integer may hold a bool, a float, a string, or
nothing at all. The standard conversions are too permissive for that: ``int``
accepts a numeric string and silently truncates a fractional float, and ``bool``
is an ``int`` subclass, so a naive check treats ``True`` as the integer one.

The helpers here reject rather than repair. A caller reading a port, a process
id, a heartbeat, or a nested object wants to know the field was absent or wrong
so it can treat the record as malformed, not to receive a plausible value
derived from something the writer never meant as one.
"""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

__all__ = [
    "coerce_int",
    "coerce_object_list",
    "coerce_object_mapping",
    "coerce_string_list",
]

_OBJECT_MAPPING: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])
_OBJECT_LIST: TypeAdapter[list[object]] = TypeAdapter(list[object])
_STRING_LIST: TypeAdapter[list[str]] = TypeAdapter(list[str])


def coerce_int(value: object) -> int | None:
    """Return *value* as an ``int``, or ``None`` when it is not one.

    Accepts an ``int``, and a ``float`` that is exactly integral. Rejects
    ``bool`` despite it being an ``int`` subclass, because a JSON ``true`` in a
    numeric field is a malformed record rather than the integer one. Rejects
    numeric strings, fractional floats, and every other type.

    Args:
        value: A parsed JSON scalar of unknown type.

    Returns:
        The integer value, or ``None`` when *value* is not strictly an integer.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def coerce_object_mapping(value: object) -> dict[str, object] | None:
    """Return *value* as a string-keyed object mapping, or ``None`` when it is not one.

    Applies at every trust boundary that hands this project an already-parsed
    JSON-shaped value - a JSON-decoded metadata blob, a LangGraph checkpoint or
    interrupt payload, an ``app.state`` field - where the value's exact shape is
    unknown until inspected. Validated ``strict``: a ``Mapping`` that is not a
    ``dict`` (e.g. ``MappingProxyType``, a hand-rolled ``Mapping``) is refused
    rather than silently copied into one. Every value actually parsed JSON or a
    LangGraph state channel produces in this project is already a plain ``dict``,
    so a non-``dict`` ``Mapping`` reaching here means the caller's assumption
    about where the value came from was wrong - worth surfacing, not smoothing
    over.

    Args:
        value: A parsed JSON scalar or unstructured runtime value of unknown type.

    Returns:
        A shallow ``dict`` copy of *value*, or ``None`` when *value* is not a
        string-keyed ``dict``.
    """
    try:
        return _OBJECT_MAPPING.validate_python(value, strict=True)
    except ValidationError:
        return None


def coerce_object_list(value: object) -> list[object] | None:
    """Return *value* as a list, or ``None`` when it is not one.

    The list-shaped counterpart to :func:`coerce_object_mapping`; the same
    strict, reject-rather-than-repair posture applies for the same reason.

    Args:
        value: A parsed JSON scalar or unstructured runtime value of unknown type.

    Returns:
        A shallow ``list`` copy of *value*, or ``None`` when *value* is not a
        ``list``.
    """
    try:
        return _OBJECT_LIST.validate_python(value, strict=True)
    except ValidationError:
        return None


def coerce_string_list(value: object, *, drop_empty: bool = False) -> list[str] | None:
    """Return *value* as a list of strings, or ``None`` when it is not one.

    Strict in the same direction as its siblings, and the distinction is worth
    stating because the opposite posture also exists in this project: a list
    holding one non-string member is refused WHOLE, never filtered down to the
    string members it happens to contain. A caller that asked for a list of
    strings and got a mixed one is reading a record its writer did not produce,
    and quietly keeping the readable half would hand it a value no writer wrote.

    Args:
        value: A parsed JSON scalar or unstructured runtime value of unknown type.
        drop_empty: Whether to drop empty strings from an otherwise valid list.
            Every field read through here names identifiers, and the empty name
            is not one; admitting it lets a blank travel on as though it were an
            id. It is an argument rather than a second function because it is
            the only axis on which the callers ever differed.

    Returns:
        A ``list`` of the validated strings, or ``None`` when *value* is not a
        list of strings. ``None`` and not an empty list even under *drop_empty*:
        an empty list is a legitimate answer a writer can produce, so returning
        it for a malformed field would fuse "named nothing" with "was not a
        string list" and destroy a distinction no caller could then recover. A
        caller that genuinely does not need the distinction spells that ``or []``
        at its own site, which is a policy it owns rather than one imposed here.
    """
    try:
        strings = _STRING_LIST.validate_python(value, strict=True)
    except ValidationError:
        return None
    return [item for item in strings if item] if drop_empty else strings
