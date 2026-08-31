"""Bounding, redaction, and grapheme safety of the probed server's stderr tail.

The tail is elided from the left, so the cut lands at an arbitrary character
offset in whatever the server wrote. Two things can go wrong there and neither
shows up in ASCII: the elision marker can be added on top of a full-width slice
and push the result past its own ceiling, and the cut can strand a combining mark
whose base character was just discarded - which then renders onto the marker
rather than as itself.

The tail is also the last point this text is under our control: it is embedded
into a refusal that reaches a client-visible failure reason, and the servers it
describes include runtime-acquired ones. So what a failing child wrote about its
own configuration is masked here, before the cut - the two operations interact,
and only one order is safe.
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


@pytest.mark.parametrize(
    ("line", "must_not_contain"),
    [
        ("ANTHROPIC_AUTH_TOKEN=sk-ant-secret", "sk-ant-secret"),
        ("Authorization: Bearer sk-live-9f8e7d", "sk-live-9f8e7d"),
        ("OPENAI_API_KEY: sk-proj-zzz", "sk-proj-zzz"),
        ("my_password = hunter2", "hunter2"),
        ("VAULTSPEC_A2A_GATEWAY_TOKEN=abc123", "abc123"),
    ],
)
def test_credential_shapes_are_masked_in_the_tail(
    line: str, must_not_contain: str
) -> None:
    """Every shape the sibling lane masks is masked here too."""
    tail = _tail_of(line)

    assert must_not_contain not in tail
    assert "<redacted>" in tail


def test_an_ordinary_diagnostic_reaches_the_tail_intact() -> None:
    """The admitted case: a tail with nothing to mask arrives whole.

    Redaction that ate the diagnostic would defeat the only reason the tail is
    retained, and a masking-only assertion cannot tell that outcome apart from
    one where there was nothing to mask.
    """
    diagnostic = (
        "error: no interpreter found for python 3.13\n"
        "resolved 0 packages in 12ms\n"
        "server exited with code 2"
    )

    assert _tail_of(diagnostic) == diagnostic


def test_a_credential_cut_by_the_bound_leaves_no_unredacted_fragment() -> None:
    """Masking must precede the cut, or the cut leaves a bare value behind.

    A credential straddling the elision point loses the NAME that introduces it
    to the discarded half, so a redactor applied to the surviving half has
    nothing left to recognise: the tail would then open on a raw fragment of the
    value. The payload places the cut inside the value on purpose.
    """
    budget = _STDERR_TAIL_CHARS - len(_STDERR_ELISION)
    secret = "sk-live-" + "z" * 40
    survivor = 20  # How much of the value a naive left cut would have kept.
    lead = "a" * 200
    trailer = "b" * (budget - survivor)
    payload = f"{lead}AUTH_TOKEN={secret}{trailer}"
    assert len(payload) > _STDERR_TAIL_CHARS, "payload does not trigger a cut"

    # Guard the guard: confirm the raw slice really would strand the fragment.
    stranded = payload[-budget:]
    assert stranded.startswith(secret[-survivor:]), (
        "test payload does not reproduce the defect it asserts against"
    )

    tail = _tail_of(payload)

    assert secret[-survivor:] not in tail
    assert secret not in tail
    assert len(tail) <= _STDERR_TAIL_CHARS


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
