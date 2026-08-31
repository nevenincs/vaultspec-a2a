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

from ....thread.clarification import MAX_RUN_MESSAGE_CHARS
from ..gateway import (
    ProviderCatalogSelection,
    RunClarificationRespondRequest,
    RunStartRequest,
)

_SELECTION = ProviderCatalogSelection(
    schema_version=1,
    provider_id="codex",
    execution_mode="app-server",
    catalog_revision="revision-1",
    entry_id="entry-1",
)


def _run_start(message: str, **changes: object) -> RunStartRequest:
    payload = {
        "team_preset": "preset",
        "message": message,
        "run_id": "message-bound",
        "selection": _SELECTION,
        **changes,
    }
    return RunStartRequest.model_validate(payload)


# Genuine multibyte samples: CJK at three UTF-8 bytes, an astral-plane emoji at
# four, and a combining sequence whose character count differs from its visible
# length. ASCII is absent on purpose - it is the case that passes either way, and
# so the case that let this class of bug survive.
_MULTIBYTE = [
    pytest.param("中", 3, id="cjk"),
    pytest.param("\U0001f600", 4, id="astral"),
    pytest.param("é", 2, id="combining"),
]

# The contract numbers, written out rather than imported.
#
# Every other assertion in this file sizes its input FROM
# ``MAX_RUN_MESSAGE_CHARS``, so the pair moves together and the bound's value is
# whatever the schema currently says: the file passes unchanged with the bound at
# 4096. That is fine for the unit checks - they are about characters versus bytes,
# not about the number - but it leaves the number itself unpinned, and the number
# is half of a cross-repo contract. A consumer sizing a buffer cannot re-derive it
# from our module, so it is stated here independently and must be changed in two
# places deliberately.
_CONTRACT_MESSAGE_CHARS = 65536
# The byte budget ``RunStartRequest.message`` publishes for a byte-counting
# consumer. UTF-8 spends at most four bytes on a character, so this is the exact
# worst case of the character bound above, not an estimate.
_CONTRACT_MESSAGE_BYTE_BUDGET = 262144


def test_the_published_character_bound_is_the_contract_number() -> None:
    """The bound a consumer was told to apply is the bound this schema applies.

    Held against a literal because the two sides of this contract live in
    different repositories: a consumer cannot import the constant, so a change
    here that is not also made there silently splits the bound in two.
    """
    assert MAX_RUN_MESSAGE_CHARS == _CONTRACT_MESSAGE_CHARS


def test_the_published_byte_budget_follows_from_the_character_bound() -> None:
    """The schema's documented byte budget must be the character bound's worst case.

    ``RunStartRequest.message`` tells a byte-counting consumer to budget
    262144 bytes. That figure is prose in the schema, so nothing recomputes it
    when the character bound moves; this is what makes the two disagree loudly
    instead of quietly.
    """
    assert _CONTRACT_MESSAGE_BYTE_BUDGET == MAX_RUN_MESSAGE_CHARS * 4


@pytest.mark.parametrize(("filler", "utf8_width"), _MULTIBYTE)
def test_message_bound_counts_characters_not_bytes(
    filler: str, utf8_width: int
) -> None:
    """A full-length multibyte prompt is accepted, as an ASCII one would be."""
    message = filler * MAX_RUN_MESSAGE_CHARS
    request = _run_start(message)

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
        _run_start(filler * (MAX_RUN_MESSAGE_CHARS + 1))


def test_documented_byte_budget_covers_the_character_bound() -> None:
    """No prompt this schema admits can overrun the published byte budget.

    A consumer sizing a buffer from the schema's documented figure must not be
    overrun by anything we accept. The widest prompt admissible is
    ``MAX_RUN_MESSAGE_CHARS`` astral-plane characters at four bytes each, and it
    is checked against the budget written down above rather than against a figure
    recomputed from the same constant - ``len(x) <= len(x)`` is a fact about
    UTF-8, true of any bound, and would hold just as well if the schema and the
    published budget had drifted apart.
    """
    widest = "\U0001f600" * MAX_RUN_MESSAGE_CHARS
    accepted = _run_start(widest).message

    assert len(accepted.encode("utf-8")) == _CONTRACT_MESSAGE_BYTE_BUDGET


def test_clarification_response_requires_exactly_one_resolution_shape() -> None:
    """Answers, a new prompt, and a decline are alternatives, never a merge."""
    answers = RunClarificationRespondRequest(answers={"scope": "backend"})
    continuation = RunClarificationRespondRequest(prompt="Use your own judgement.")
    decline = RunClarificationRespondRequest(decline=True)

    assert answers.answers == {"scope": "backend"}
    assert answers.prompt is None
    assert continuation.prompt == "Use your own judgement."
    assert continuation.answers is None
    assert decline.decline is True
    assert decline.answers is None
    assert decline.prompt is None

    with pytest.raises(ValidationError):
        RunClarificationRespondRequest()
    with pytest.raises(ValidationError):
        RunClarificationRespondRequest(
            answers={"scope": "backend"}, prompt="Ignore that answer."
        )
    with pytest.raises(ValidationError):
        RunClarificationRespondRequest(answers={"scope": "backend"}, decline=True)
    with pytest.raises(ValidationError):
        RunClarificationRespondRequest(prompt="Also chat about it.", decline=True)


def test_clarification_decline_admits_only_the_literal_true() -> None:
    """``decline: false`` is a contradiction, not an empty resolution.

    Validated through ``model_validate`` because that is how a wire payload
    arrives: the annotation already refuses the literal at the type level, and
    this proves the runtime boundary refuses it too.
    """
    with pytest.raises(ValidationError):
        RunClarificationRespondRequest.model_validate({"decline": False})


@pytest.mark.parametrize("prompt", ["", " ", "\t\r\n"])
def test_clarification_continuation_rejects_blank_wire_prompts(prompt: str) -> None:
    """The HTTP contract cannot turn a local composer switch into a resume."""
    with pytest.raises(ValidationError):
        RunClarificationRespondRequest(prompt=prompt)


def test_clarification_continuation_enforces_the_wire_character_ceiling() -> None:
    """The continuation alternative shares the inclusive new-turn text budget."""
    prompt = "世" * MAX_RUN_MESSAGE_CHARS

    assert RunClarificationRespondRequest(prompt=prompt).prompt == prompt
    with pytest.raises(ValidationError):
        RunClarificationRespondRequest(prompt=prompt + "x")


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
    request = _run_start(
        "hello",
        title=filler * 200,
        feature_tag=filler * 128,
    )
    assert request.title == filler * 200
    assert request.feature_tag == filler * 128
