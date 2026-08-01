"""A preset declares the questions its runs ask, and bad declarations refuse.

The questions are preset-declared and never inferred: no layer reads the user's
prompt and decides what to ask. A preset that declares a questionnaire asks it; a
preset that declares none behaves exactly as it did before.

The bounds are NOT restated here. The declaration is validated by constructing
the same request the wire carries, so a preset can only declare something the
interrupt payload could legally hold - one set of rules, enforced once, with the
config layer inheriting them rather than duplicating them.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from ...thread.clarification import (
    MAX_OPTIONS_PER_QUESTION,
    MAX_QUESTIONS_PER_REQUEST,
    ClarificationKind,
)
from ...thread.errors import ConfigError
from ..team_config import TeamConfig, load_team_config

_PRESET_DIR = Path(__file__).resolve().parents[1] / "presets" / "teams"


def _base_team(**clarification: Any) -> dict[str, Any]:
    """A minimal valid research_adr team, optionally declaring a questionnaire."""
    team: dict[str, Any] = {
        "id": "probe-team",
        "display_name": "Probe",
        "topology": {"type": "research_adr", "order": []},
        "workers": [
            {"agent_id": "vaultspec-researcher"},
            {"agent_id": "vaultspec-synthesist"},
            {"agent_id": "vaultspec-adr-author"},
            {"agent_id": "vaultspec-doc-reviewer"},
        ],
    }
    if clarification:
        team["clarification"] = clarification
    return team


def _question(**overrides: Any) -> dict[str, Any]:
    question: dict[str, Any] = {
        "id": "scope",
        "kind": "choice",
        "prompt": "Which surface should this cover?",
        "options": ["frontend", "backend", "both"],
        "required": True,
    }
    question.update(overrides)
    return question


# ---------------------------------------------------------------------------
# The declaration is honoured
# ---------------------------------------------------------------------------


def test_a_declared_questionnaire_is_loaded_and_typed() -> None:
    """A declared block reaches the config as the SAME type the wire carries."""
    team = TeamConfig.model_validate(_base_team(questions=[_question()]))

    assert team.clarification is not None
    question = team.clarification.questions[0]
    assert question.id == "scope"
    assert question.kind is ClarificationKind.CHOICE
    assert question.options == ["frontend", "backend", "both"]
    assert question.required is True


def test_a_preset_declaring_nothing_has_no_questionnaire() -> None:
    """Absence is the default, so an existing preset is untouched."""
    assert TeamConfig.model_validate(_base_team()).clarification is None


def test_declaring_the_block_with_no_questions_is_refused() -> None:
    """An empty declaration is a no-op that reads as intent, so it is refused.

    Allowing it would leave a preset asserting "this run asks" while arming
    nothing - the reader would have to check the question list to learn that the
    block means the opposite of what it says. Absence already expresses "do not
    ask", so the empty block has no honest meaning left to carry.
    """
    with pytest.raises((ValueError, ConfigError)):
        TeamConfig.model_validate(_base_team(questions=[]))


# ---------------------------------------------------------------------------
# Bad declarations refuse to load, rather than being silently trimmed
# ---------------------------------------------------------------------------


def test_a_declaration_of_an_unknown_key_is_refused() -> None:
    """The silent-drop failure this whole feature nearly shipped with.

    Before the schema existed, a preset could declare a questionnaire and be
    loaded WITHOUT ERROR while the block was discarded - the run would simply
    never ask. Refusing an unknown key is what makes a typo loud.
    """
    with pytest.raises((ValueError, ConfigError)):
        TeamConfig.model_validate(_base_team(questionz=[_question()]))


def test_more_questions_than_the_cap_is_refused_not_truncated() -> None:
    """Silently trimming would ask a different questionnaire than was declared."""
    too_many = [
        _question(id=f"q{index}") for index in range(MAX_QUESTIONS_PER_REQUEST + 1)
    ]
    with pytest.raises((ValueError, ConfigError)):
        TeamConfig.model_validate(_base_team(questions=too_many))


def test_more_options_than_the_cap_is_refused() -> None:
    options = [f"opt{index}" for index in range(MAX_OPTIONS_PER_QUESTION + 1)]
    with pytest.raises((ValueError, ConfigError)):
        TeamConfig.model_validate(_base_team(questions=[_question(options=options)]))


def test_a_choice_without_options_is_refused() -> None:
    with pytest.raises((ValueError, ConfigError)):
        TeamConfig.model_validate(
            _base_team(questions=[_question(options=None)]),
        )


def test_a_text_question_carrying_options_is_refused() -> None:
    with pytest.raises((ValueError, ConfigError)):
        TeamConfig.model_validate(
            _base_team(questions=[_question(kind="text", options=["a"])]),
        )


def test_duplicate_question_ids_are_refused() -> None:
    """Answers are keyed by id, so two questions sharing one is unanswerable."""
    with pytest.raises(ConfigError, match="clarification"):
        TeamConfig.model_validate(
            _base_team(questions=[_question(), _question()]),
        )


def test_a_duplicate_option_is_refused() -> None:
    with pytest.raises((ValueError, ConfigError)):
        TeamConfig.model_validate(
            _base_team(questions=[_question(options=["same", "same"])]),
        )


# ---------------------------------------------------------------------------
# Shipping presets
# ---------------------------------------------------------------------------


def test_every_shipping_preset_still_loads() -> None:
    """Adding the block must not disturb a preset that never declares it."""
    for path in sorted(_PRESET_DIR.glob("*.toml")):
        if path.stem == "mock-invalid":
            continue  # deliberately malformed fixture
        load_team_config(path.stem)


def test_the_declaring_preset_declares_a_loadable_questionnaire() -> None:
    """The shipped example is real: it parses, and it is within the caps."""
    path = _PRESET_DIR / "vaultspec-adr-research-clarify.toml"
    assert path.is_file(), "the declaring preset must exist"

    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    declared = raw["team"]["clarification"]["questions"]
    assert 1 <= len(declared) <= MAX_QUESTIONS_PER_REQUEST

    team = load_team_config(path.stem)
    assert team.clarification is not None
    assert len(team.clarification.questions) == len(declared)
