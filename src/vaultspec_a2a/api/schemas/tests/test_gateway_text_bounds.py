"""The unit of every free-text bound on the gateway schema.

Each bound below is declared in CHARACTERS. That choice is load-bearing rather
than incidental: these fields carry human prose, and a bound re-expressed in
bytes would silently shrink to a third or a quarter of itself the moment the
prose stopped being English, refusing a Japanese or emoji author input an
English one supplies freely. These tests pin the unit so the substitution cannot
be made quietly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ..gateway import MAX_RUN_MESSAGE_CHARS, RunStartRequest

# Genuine multibyte samples: CJK at three UTF-8 bytes, an astral-plane emoji at
# four, and a combining sequence whose character count differs from its visible
# length. ASCII is absent on purpose - it is the case that passes either way, and
# so the case that let this class of bug survive.
_MULTIBYTE = [
    pytest.param("中", 3, id="cjk"),
    pytest.param("\U0001f600", 4, id="astral"),
    pytest.param("é", 2, id="combining"),
]


@pytest.mark.parametrize(("filler", "utf8_width"), _MULTIBYTE)
def test_message_bound_counts_characters_not_bytes(
    filler: str, utf8_width: int
) -> None:
    """A full-length multibyte prompt is accepted, as an ASCII one would be."""
    message = filler * MAX_RUN_MESSAGE_CHARS
    request = RunStartRequest(team_preset="preset", message=message)

    assert len(request.message) == MAX_RUN_MESSAGE_CHARS
    # The prompt genuinely exceeds the character bound when measured in bytes,
    # which is precisely what a byte-counting consumer would trip over.
    assert len(request.message.encode("utf-8")) == MAX_RUN_MESSAGE_CHARS * utf8_width
    assert request.message == message


@pytest.mark.parametrize(("filler", "utf8_width"), _MULTIBYTE)
def test_message_bound_rejects_one_character_past_the_cap(
    filler: str, utf8_width: int
) -> None:
    """The bound still binds - it is a character bound, not an absent one."""
    del utf8_width
    with pytest.raises(ValidationError):
        RunStartRequest(
            team_preset="preset", message=filler * (MAX_RUN_MESSAGE_CHARS + 1)
        )


def test_documented_byte_budget_covers_the_character_bound() -> None:
    """The byte figure the schema publishes must cover the worst-case prompt.

    ``RunStartRequest.message`` tells a byte-counting consumer to budget
    ``MAX_RUN_MESSAGE_CHARS * 4``. UTF-8 spends at most four bytes on a character,
    so that budget is exact rather than optimistic; a consumer sizing a buffer
    from it cannot be overrun by any prompt this schema admits.
    """
    widest = "\U0001f600" * MAX_RUN_MESSAGE_CHARS
    accepted = RunStartRequest(team_preset="preset", message=widest).message
    assert len(accepted.encode("utf-8")) <= MAX_RUN_MESSAGE_CHARS * 4


@pytest.mark.parametrize(("filler", "utf8_width"), _MULTIBYTE)
def test_title_and_feature_tag_accept_multibyte_prose(
    filler: str, utf8_width: int
) -> None:
    """Neither field constrains prose to an ASCII alphabet.

    A title is display prose and a feature tag is author-chosen, so an ASCII-only
    character class on either would reject legitimate input. Only the run id -
    which must stay path-safe - carries such a class.
    """
    del utf8_width
    request = RunStartRequest(
        team_preset="preset",
        message="hello",
        title=filler * 200,
        feature_tag=filler * 128,
    )
    assert request.title == filler * 200
    assert request.feature_tag == filler * 128
