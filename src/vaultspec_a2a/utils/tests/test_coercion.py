"""Strict integer coercion must reject, not repair.

Two modules parsing untrusted JSON had grown byte-identical coercion helpers.
The behaviour they share is subtle enough to be worth pinning once: a JSON
``true`` is an ``int`` subclass in Python and would otherwise coerce to one, and
a numeric string or a fractional float would silently become a plausible number
the writer never wrote.
"""

from __future__ import annotations

import pytest

from ..coercion import coerce_int


@pytest.mark.parametrize("value", [0, 1, -7, 2**40])
def test_an_integer_passes_through(value: int) -> None:
    """An honest integer is returned unchanged, including zero and negatives."""
    assert coerce_int(value) == value


@pytest.mark.parametrize("value", [3.0, -2.0, 0.0])
def test_an_integral_float_is_accepted(value: float) -> None:
    """JSON has one number type, so an integral float is a legitimate integer."""
    result = coerce_int(value)

    assert result == int(value)
    assert isinstance(result, int)


@pytest.mark.parametrize("value", [True, False])
def test_a_bool_is_rejected_despite_being_an_int_subclass(value: bool) -> None:
    """A JSON true in a numeric field is a malformed record, not the integer one."""
    assert coerce_int(value) is None


@pytest.mark.parametrize("value", [1.5, -0.25])
def test_a_fractional_float_is_rejected_rather_than_truncated(value: float) -> None:
    """Truncating would invent a value the writer never sent."""
    assert coerce_int(value) is None


@pytest.mark.parametrize("value", ["1", "", "abc", None, [], {}, object()])
def test_every_other_type_is_rejected(value: object) -> None:
    """A numeric string is the dangerous case: int() would accept it."""
    assert coerce_int(value) is None
