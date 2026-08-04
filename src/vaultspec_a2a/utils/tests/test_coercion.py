"""Strict coercion of untrusted JSON-shaped values must reject, not repair.

Several modules parsing untrusted JSON had grown byte-identical coercion
helpers. The behaviour they share is subtle enough to be worth pinning once: a
JSON ``true`` is an ``int`` subclass in Python and would otherwise coerce to
one, and a numeric string or a fractional float would silently become a
plausible number the writer never wrote. The object and list narrowers pin the
same discipline one level up: ``strict=True`` refuses a ``Mapping``/``Sequence``
that is not literally a ``dict``/``list`` rather than silently copying it into
one, because every value this project's own JSON decoding or LangGraph state
channels ever produce is already a plain ``dict`` or ``list`` - a caller handing
in anything else is a sign its assumption about the value's provenance was
wrong.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from ..coercion import coerce_int, coerce_object_list, coerce_object_mapping


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


class _HandRolledMapping(Mapping[str, object]):
    """A genuine ``Mapping`` that is deliberately NOT a ``dict`` subclass."""

    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def test_a_plain_dict_passes_through_as_a_copy() -> None:
    """An honest ``dict`` is accepted; the result is a distinct shallow copy."""
    original = {"a": 1, "b": 2}

    result = coerce_object_mapping(original)

    assert result == original
    assert result is not original


def test_a_dict_subclass_is_accepted() -> None:
    """``OrderedDict`` etc. are ``dict`` subclasses and pass strict validation."""
    result = coerce_object_mapping(OrderedDict(a=1, b=2))

    assert result == {"a": 1, "b": 2}


@pytest.mark.parametrize(
    "value",
    [
        MappingProxyType({"a": 1}),
        _HandRolledMapping({"a": 1}),
    ],
)
def test_a_mapping_that_is_not_a_dict_is_refused(value: Mapping[str, object]) -> None:
    """Strict validation refuses to silently copy a non-``dict`` ``Mapping``.

    A caller handing this narrower a ``MappingProxyType`` or a hand-rolled
    ``Mapping`` is a sign its assumption about the value's provenance (parsed
    JSON, a LangGraph state channel) was wrong; that is worth surfacing as a
    refusal rather than smoothing over with a coercing copy.
    """
    assert coerce_object_mapping(value) is None


@pytest.mark.parametrize(
    "value",
    [None, "not a dict", [("a", 1)], {1: "x"}, {"a": 1, 2: "y"}, object()],
)
def test_a_non_object_value_is_refused(value: object) -> None:
    """None, scalars, non-string-keyed dicts, and pair-lists are all refused."""
    assert coerce_object_mapping(value) is None


def test_a_plain_list_passes_through_as_a_copy() -> None:
    """An honest ``list`` is accepted; the result is a distinct shallow copy."""
    original = [1, "two", {"three": 3}]

    result = coerce_object_list(original)

    assert result == original
    assert result is not original


@pytest.mark.parametrize("value", [(1, 2), {1, 2}, "ab", None, {"a": 1}, object()])
def test_a_non_list_value_is_refused(value: object) -> None:
    """A tuple or set is Sequence-shaped but not a ``list``, and is refused too."""
    assert coerce_object_list(value) is None
