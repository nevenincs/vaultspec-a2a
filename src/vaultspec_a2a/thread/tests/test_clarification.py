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
    strip_control_characters,
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
    """One character past the cap is refused on all three strings."""
    with pytest.raises(ValidationError):
        _choice(prompt="x" * (MAX_PROMPT_CHARS + 1))
    with pytest.raises(ValidationError):
        _choice(options=["x" * (MAX_OPTION_CHARS + 1)])
    with pytest.raises(ValidationError):
        ClarificationAnswers(
            request_id="clarify-1", answers={"scope": "x" * (MAX_ANSWER_CHARS + 1)}
        )


def test_a_string_of_exactly_the_cap_is_admitted() -> None:
    """The cap is inclusive, and the refusal test above cannot show that.

    A cap is two behaviours, and asserting only the refusal leaves the boundary
    itself untested: a bound that was one character too strict would refuse the
    longest legal string and every ``MAX + 1`` assertion above would still pass.

    Not symmetry for its own sake. The producer truncates an over-long proposal
    to exactly the cap (``strip_control_characters(text)[:max_chars]``), so a
    model that over-writes a prompt yields a string of precisely this length. If
    the cap were exclusive, that truncated question would be refused at
    construction and silently dropped - every over-long proposal lost, and lost
    quietly, because the producer degrades rather than raises.
    """
    assert len(_choice(prompt="x" * MAX_PROMPT_CHARS).prompt) == MAX_PROMPT_CHARS

    options = _choice(options=["x" * MAX_OPTION_CHARS]).options or []
    assert len(options[0]) == MAX_OPTION_CHARS

    answers = ClarificationAnswers(
        request_id="clarify-1", answers={"scope": "x" * MAX_ANSWER_CHARS}
    )
    assert len(answers.answers["scope"]) == MAX_ANSWER_CHARS


@pytest.mark.parametrize(
    "text",
    [
        "two\nlines",
        "carriage\rreturn",
        "vertical\x0btab",
        "form\x0cfeed",
        "nul\x00byte",
        "delete\x7fchar",
        "c1\x85next",
    ],
)
def test_no_clarification_string_may_carry_a_control_character(text: str) -> None:
    """The rule binds every clarification string, in both directions.

    Enforced on the annotations rather than on the HTTP schema, so a question
    minted in-process is held to it exactly as an answer arriving on the route
    is. DEL and the C1 range are in scope alongside the familiar C0 breaks -
    the rule is the Unicode ``Cc`` category, not a hand-picked block.
    """
    with pytest.raises(ValidationError, match="control characters"):
        ClarificationAnswers(request_id="clarify-1", answers={"scope": text})
    with pytest.raises(ValidationError, match="control characters"):
        _choice(prompt=text)
    with pytest.raises(ValidationError, match="control characters"):
        _choice(options=[text])


def test_a_tab_is_refused_like_any_other_control_character() -> None:
    """Tab is not excepted, and the exception would have stranded runs.

    Called out on its own because it is the surprising half of the rule. An
    option label is offered verbatim and an answer must match an option
    verbatim, so admitting a tab in a label while any consumer of the answer
    refuses one makes that option unselectable - the only string that could
    match is one that cannot be submitted, and the run parks on a question
    nobody can answer. A single-line string loses nothing by dropping tab.
    """
    with pytest.raises(ValidationError, match="control characters"):
        _choice(options=["tab\tseparated"])
    with pytest.raises(ValidationError, match="control characters"):
        ClarificationAnswers(request_id="clarify-1", answers={"scope": "tab\tin"})


@pytest.mark.parametrize("answer", ["plain prose", "unicode - naive", "  spaced  ", ""])
def test_ordinary_text_is_taken_unchanged(answer: str) -> None:
    """The rule refuses control characters and nothing else.

    Ordinary whitespace, punctuation, and non-ASCII prose are untouched: a
    boundary that quietly narrowed what a human may type would be a worse
    failure than the one it replaced.
    """
    answers = ClarificationAnswers(request_id="clarify-1", answers={"scope": answer})
    assert answers.answers["scope"] == answer


def test_the_strip_and_the_refusal_share_one_rule() -> None:
    """The coercing half and the refusing half agree on what they act on.

    Question text proposed by a model turn is stripped, because dropping a
    stray character beats losing the question; an answer is refused, because
    silently rewriting what a human typed could turn it into a different answer
    than the one they gave. Two dispositions are intended; two DEFINITIONS of
    "control character" are not, so what one strips is exactly what the other
    refuses - asserted here by feeding the strip's own output back through the
    refusal.
    """
    hostile = "keep\nthis\ttext\x00clean"
    stripped = strip_control_characters(hostile)

    assert stripped == "keepthistextclean"
    with pytest.raises(ValidationError, match="control characters"):
        ClarificationAnswers(request_id="clarify-1", answers={"scope": hostile})

    admitted = ClarificationAnswers(request_id="clarify-1", answers={"scope": stripped})
    assert admitted.answers["scope"] == stripped


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
