"""Bounding and grapheme safety of the probed server's stderr tail.

The tail is elided from the left, so the cut lands at an arbitrary character
offset in whatever the server wrote. Two things can go wrong there and neither
shows up in ASCII: the elision marker can be added on top of a full-width slice
and push the result past its own ceiling, and the cut can strand a combining mark
whose base character was just discarded - which then renders onto the marker
rather than as itself.
"""

from __future__ import annotations

import io
import unicodedata

import pytest

from .._mcp_contract import _STDERR_ELISION, _STDERR_TAIL_CHARS, _stderr_tail

_PREFIX = " Server stderr: "


def _tail_of(text: str) -> str:
    """Drive the real seam with a real seekable text handle."""
    captured = io.StringIO(text)
    result = _stderr_tail(captured)
    assert result.startswith(_PREFIX)
    return result.removeprefix(_PREFIX)


@pytest.mark.parametrize(
    ("label", "filler"),
    [
        ("ascii", "a"),
        ("cjk", "中"),
        ("astral", "\U0001f600"),
    ],
)
def test_elided_tail_respects_its_own_ceiling(label: str, filler: str) -> None:
    """The marker is inside the budget, not added on top of a full-width slice."""
    tail = _tail_of(filler * (_STDERR_TAIL_CHARS * 2))

    assert len(tail) <= _STDERR_TAIL_CHARS, (
        f"{label} tail is {len(tail)} chars, over the {_STDERR_TAIL_CHARS} ceiling"
    )
    assert tail.startswith(_STDERR_ELISION)


def test_short_stderr_is_returned_whole_without_a_marker() -> None:
    """Nothing is elided when nothing needs to be."""
    assert _tail_of("boom") == "boom"


def test_multibyte_stderr_survives_as_characters() -> None:
    """A short non-ASCII diagnostic round-trips rather than arriving mangled."""
    message = "サーバーの起動に失敗しました"
    assert _tail_of(message) == message


def test_cut_never_strands_a_combining_mark_onto_the_marker() -> None:
    """A mark whose base was cut away must not compose onto the elision marker.

    The accent is written as an explicit DECOMPOSED sequence - base ``e`` plus
    U+0301 - because the precomposed single-character form cannot be split by any
    cut, and using it would leave this test unable to fail.
    """
    budget = _STDERR_TAIL_CHARS - len(_STDERR_ELISION)
    # The payload must exceed the ceiling (or no cut happens at all) AND place
    # the combining mark exactly at the cut, so the base "e" is the last
    # character discarded and the accent the first one kept.
    payload = "X" * 10 + "é" + "z" * (budget - 1)
    assert len(payload) > _STDERR_TAIL_CHARS, "payload does not trigger a cut"

    # Guard the guard: confirm the raw slice really would strand the mark.
    stranded = payload[-budget:]
    assert unicodedata.combining(stranded[0]), (
        "test payload does not reproduce the defect it asserts against"
    )

    tail = _tail_of(payload)

    first = tail.removeprefix(_STDERR_ELISION)[0]
    assert not unicodedata.combining(first), (
        f"tail begins with combining mark U+{ord(first):04X}, which renders onto "
        f"the elision marker instead of as itself"
    )
    assert len(tail) <= _STDERR_TAIL_CHARS
