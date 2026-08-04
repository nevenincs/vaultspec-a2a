"""Reading one required field out of a service response a test just received.

A live-service test asserts on a real JSON body, and the first thing it must do
with any field is establish that the field is present AND the type the contract
promises. Written inline that is three lines and a message per field, so four
service suites had each written the same two readers for themselves - identical
bodies, identical failure text, four times over.

The failure text is the reason these are worth sharing rather than inlining. A
service test that reads a wrong-typed field fails somewhere far from the request
that produced it, so the message has to carry WHERE: an ``at`` locator naming the
response and the path within it, plus the offending value repr. Four independent
copies of that convention drift, and a drifted locator is a test whose failure no
longer tells you which call went wrong.

These raise ``AssertionError`` because that is what they are - an assertion about
a payload, not a type error in the caller. The sibling narrowing helpers in these
same suites are deliberately NOT here: those split across two error vocabularies
(``AssertionError`` in some suites, ``TypeError`` in others) and at least two
suites self-test which one they raise, so their exception type is part of each
module's contract rather than incidental. Collapsing them needs a decision about
that dialect, which is a separate change from removing an exact duplicate.
"""

from __future__ import annotations

__all__ = ["required_bool", "required_text"]


def required_text(body: dict[str, object], field: str, *, at: str) -> str:
    """Read one required text field from a validated service payload."""
    value = body.get(field)
    if not isinstance(value, str):
        raise AssertionError(f"{at}.{field} was not text: {value!r}")
    return value


def required_bool(body: dict[str, object], field: str, *, at: str) -> bool:
    """Read one required boolean field from a validated service payload."""
    value = body.get(field)
    if not isinstance(value, bool):
        raise AssertionError(f"{at}.{field} was not boolean: {value!r}")
    return value
