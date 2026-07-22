"""Strict coercion of untrusted JSON scalars.

Records arriving from a file, a peer service, or an event stream are parsed
JSON, so a field typed as an integer may hold a bool, a float, a string, or
nothing at all. The standard conversions are too permissive for that: ``int``
accepts a numeric string and silently truncates a fractional float, and ``bool``
is an ``int`` subclass, so a naive check treats ``True`` as the integer one.

The helper here rejects rather than repairs. A caller reading a port, a process
id, or a heartbeat wants to know the field was absent or wrong so it can treat
the record as malformed, not to receive a plausible number derived from a value
the writer never meant as one.
"""

from __future__ import annotations

__all__ = ["coerce_int"]


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
