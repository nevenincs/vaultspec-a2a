"""Tests for the clarification contract's bounds and validation rules.

The bounds are the contract, so what is asserted here is that they are enforced
by CONSTRUCTION - a violating question set cannot be built at all, which is what
makes a producer unable to put one on the wire. A test that only checked the
route would leave the same bound unenforced for every other producer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ..clarification import (
    CLARIFICATION_INTERRUPT_TYPE,
    MAX_ANSWER_CHARS,
    MAX_OPTION_CHARS,
    MAX_PROMPT_CHARS,
    ClarificationAnswers,
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
    pending_clarification,
    validate_clarification_answers,
)


def _choice(
    question_id: str = "scope",
    *,
    prompt: str = "Which framing did you mean?",
    options: list[str] | None = None,
    required: bool = True,
) -> ClarificationQuestion:
    return ClarificationQuestion(
        id=question_id,
        prompt=prompt,
        kind=ClarificationKind.CHOICE,
        options=["a", "b"] if options is None else options,
        required=required,
    )


def _request(*questions: ClarificationQuestion) -> ClarificationRequest:
    return ClarificationRequest(
        request_id="clarify-1", questions=list(questions) or [_choice()]
    )


# ---------------------------------------------------------------------------
# Cardinality bounds
# ---------------------------------------------------------------------------


def test_at_most_four_questions_per_request() -> None:
    four = [_choice(f"q{index}") for index in range(4)]
    assert len(_request(*four).questions) == 4

    with pytest.raises(ValidationError, match="at most 4"):
        _request(*four, _choice("q4"))


def test_a_request_must_ask_something() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        ClarificationRequest(request_id="clarify-empty", questions=[])


def test_at_most_four_options_per_choice() -> None:
    assert len(_choice(options=["a", "b", "c", "d"]).options or []) == 4

    with pytest.raises(ValidationError, match="at most 4"):
        _choice(options=["a", "b", "c", "d", "e"])


def test_question_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="unique ids"):
        _request(_choice("scope"), _choice("scope"))


# ---------------------------------------------------------------------------
# String bounds
# ---------------------------------------------------------------------------


def test_prompt_option_and_answer_strings_are_capped() -> None:
    with pytest.raises(ValidationError):
        _choice(prompt="x" * (MAX_PROMPT_CHARS + 1))
    with pytest.raises(ValidationError):
        _choice(options=["x" * (MAX_OPTION_CHARS + 1)])
    with pytest.raises(ValidationError):
        ClarificationAnswers(
            request_id="clarify-1", answers={"scope": "x" * (MAX_ANSWER_CHARS + 1)}
        )


def test_identifiers_are_path_and_key_safe() -> None:
    # A question id becomes a JSON object key and a request id rides a URL path,
    # so neither may carry separators.
    with pytest.raises(ValidationError):
        _choice("scope/../etc")
    with pytest.raises(ValidationError):
        ClarificationRequest(request_id="clarify 1", questions=[_choice()])


# ---------------------------------------------------------------------------
# Kind / options coherence
# ---------------------------------------------------------------------------


def test_a_choice_must_offer_options_and_a_text_question_must_not() -> None:
    with pytest.raises(ValidationError, match="declares no options"):
        ClarificationQuestion(
            id="scope", prompt="Which?", kind=ClarificationKind.CHOICE
        )
    with pytest.raises(ValidationError, match="must not declare options"):
        ClarificationQuestion(
            id="scope", prompt="Which?", kind=ClarificationKind.TEXT, options=["a"]
        )


def test_a_choice_may_not_offer_the_same_option_twice() -> None:
    with pytest.raises(ValidationError, match="duplicate options"):
        _choice(options=["a", "a"])


def test_unknown_fields_are_refused_on_every_model() -> None:
    with pytest.raises(ValidationError):
        ClarificationQuestion(
            id="scope",
            prompt="Which?",
            kind=ClarificationKind.TEXT,
            hint="smuggled",  # ty: ignore[unknown-argument]
        )


# ---------------------------------------------------------------------------
# Answer validation against the question set
# ---------------------------------------------------------------------------


def test_valid_answers_report_no_violations() -> None:
    request = _request(
        _choice("scope"),
        ClarificationQuestion(
            id="notes",
            prompt="Anything else?",
            kind=ClarificationKind.TEXT,
            required=False,
        ),
    )
    assert validate_clarification_answers(request, {"scope": "a"}) == []
    assert validate_clarification_answers(request, {"scope": "b", "notes": "x"}) == []


def test_every_violation_is_reported_together() -> None:
    """One correction should fix a rejected sheet, not one round trip per fault."""
    request = _request(_choice("scope"), _choice("mode"))
    notes = validate_clarification_answers(
        request, {"scope": "not-an-option", "invented": "x"}
    )
    assert len(notes) == 3
    joined = " | ".join(notes)
    assert "'invented'" in joined
    assert "'scope'" in joined
    assert "'mode'" in joined


def test_a_blank_answer_does_not_satisfy_a_required_question() -> None:
    assert validate_clarification_answers(_request(_choice("scope")), {"scope": "   "})


def test_an_optional_question_that_is_answered_still_honours_its_options() -> None:
    request = _request(_choice("scope", required=False))
    assert validate_clarification_answers(request, {}) == []
    assert validate_clarification_answers(request, {"scope": "nope"})


# ---------------------------------------------------------------------------
# Lenient checkpoint parsing
# ---------------------------------------------------------------------------


def test_a_payload_round_trips_through_the_interrupt_shape() -> None:
    request = _request()
    parsed = ClarificationRequest.from_payload(request.as_interrupt_payload())
    assert parsed == request
    assert request.as_interrupt_payload()["type"] == CLARIFICATION_INTERRUPT_TYPE


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not a mapping",
        {"type": "document_approval_request", "phase": "research"},
        {"type": "clarification_request"},
        {"type": "clarification_request", "request_id": "x", "questions": []},
    ],
)
def test_an_unreadable_payload_reads_as_no_pending_question(payload: object) -> None:
    """A status read must degrade, never fail, on a payload it cannot parse.

    The input is a checkpoint this process did not necessarily write, so a shape
    from an older or newer producer has to mean "nothing pending" rather than
    breaking the recovery read that every client depends on.
    """
    assert ClarificationRequest.from_payload(payload) is None


def test_no_checkpoint_means_no_pending_question() -> None:
    assert pending_clarification(None, thread_id="run-1") is None
