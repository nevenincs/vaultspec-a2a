"""Tests for the clarification contract's bounds and validation rules.

The bounds are the contract, so what is asserted here is that they are enforced
by CONSTRUCTION - a violating question set cannot be built at all, which is what
makes a producer unable to put one on the wire. A test that only checked the
route would leave the same bound unenforced for every other producer.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ..clarification import (
    CLARIFICATION_DECLINE_MARKER,
    CLARIFICATION_INTERRUPT_TYPE,
    MAX_ANSWER_CHARS,
    MAX_OPTION_CHARS,
    MAX_PROMPT_CHARS,
    MAX_QUESTIONS_PER_REQUEST,
    MAX_RUN_MESSAGE_CHARS,
    ClarificationAnswers,
    ClarificationContinuation,
    ClarificationDecline,
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
    clarification_resolution_fingerprint,
    parse_clarification_resolution,
    pending_clarification,
    render_clarification_answers,
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


def test_a_continuation_prompt_uses_the_run_message_character_ceiling() -> None:
    """The alternate outcome has the same inclusive text budget as a new turn."""
    prompt = "世" * MAX_RUN_MESSAGE_CHARS
    continuation = ClarificationContinuation(request_id="clarify-1", prompt=prompt)

    assert continuation.prompt == prompt
    assert len(continuation.prompt.encode("utf-8")) > MAX_RUN_MESSAGE_CHARS
    assert continuation.as_resume_value() == {
        "type": "clarification_continuation",
        "request_id": "clarify-1",
        "prompt": prompt,
    }

    with pytest.raises(ValidationError):
        ClarificationContinuation(request_id="clarify-1", prompt=prompt + "x")


@pytest.mark.parametrize("prompt", ["", " ", "\t\r\n"])
def test_a_continuation_requires_real_prompt_content(prompt: str) -> None:
    """Switching composer mode is local; only submitted text is a resume value."""
    with pytest.raises(ValidationError):
        ClarificationContinuation(request_id="clarify-1", prompt=prompt)


def test_a_decline_is_payload_free_and_round_trips_through_the_parser() -> None:
    """Refusal carries identity and nothing else - there is no text to bound.

    The resume value is exactly the discriminator and the request id, and the
    strict parser reads it back as the same typed outcome; extra keys are
    refused at construction so a decline can never smuggle an answer or a
    prompt alongside itself.
    """
    decline = ClarificationDecline(request_id="clarify-1")

    assert decline.as_resume_value() == {
        "type": "clarification_decline",
        "request_id": "clarify-1",
    }
    parsed = parse_clarification_resolution(
        decline.as_resume_value(), request_id="clarify-1"
    )
    assert isinstance(parsed, ClarificationDecline)

    with pytest.raises(ValidationError):
        ClarificationDecline.model_validate(
            {
                "type": "clarification_decline",
                "request_id": "clarify-1",
                "prompt": "smuggled",
            }
        )


def test_the_decline_marker_is_a_valid_single_line_prompt() -> None:
    """The fixed transcript trace obeys the same text rules as a question.

    The marker is the one string a decline puts in front of downstream model
    turns, so it must itself be line-safe and within the prompt ceiling - a
    marker the contract's own validators would refuse elsewhere would be a
    value this module forbids everyone else from producing.
    """
    assert strip_control_characters(CLARIFICATION_DECLINE_MARKER) == (
        CLARIFICATION_DECLINE_MARKER
    )
    assert 0 < len(CLARIFICATION_DECLINE_MARKER) <= MAX_PROMPT_CHARS


def test_answers_render_in_question_order_with_only_answered_lines() -> None:
    """The transcript turn pairs each question's prompt with the human's answer.

    Order comes from the committed request, never from answer-map insertion
    order, and an unanswered or blank-answered question contributes no line -
    the rendering shows what the human actually said, nothing more.
    """
    request = ClarificationRequest(
        request_id="clarify-1",
        questions=[
            _choice("scope", prompt="Which surface?", options=["frontend", "backend"]),
            ClarificationQuestion(
                id="constraints",
                prompt="Any constraint?",
                kind=ClarificationKind.TEXT,
                required=False,
            ),
            ClarificationQuestion(
                id="deadline",
                prompt="By when?",
                kind=ClarificationKind.TEXT,
                required=False,
            ),
        ],
    )

    rendered = render_clarification_answers(
        request,
        {"constraints": "keep it small", "scope": "backend", "deadline": "  "},
    )
    assert rendered == (
        "Answers to the clarification questionnaire:\n"
        "- Which surface?: backend\n"
        "- Any constraint?: keep it small"
    )

    assert render_clarification_answers(request, {}) is None
    assert render_clarification_answers(request, {"deadline": "   "}) is None


def test_a_full_rendering_stays_inside_the_run_message_ceiling() -> None:
    """Four maximal prompt/answer pairs compose to a bounded transcript turn."""
    questions = [
        ClarificationQuestion(
            id=f"q{index}",
            prompt="p" * MAX_PROMPT_CHARS,
            kind=ClarificationKind.TEXT,
            required=True,
        )
        for index in range(MAX_QUESTIONS_PER_REQUEST)
    ]
    request = ClarificationRequest(request_id="clarify-1", questions=questions)
    rendered = render_clarification_answers(
        request,
        {question.id: "a" * MAX_ANSWER_CHARS for question in questions},
    )

    assert rendered is not None
    assert len(rendered) <= MAX_RUN_MESSAGE_CHARS


def test_resolution_parser_binds_the_resume_to_the_committed_request() -> None:
    """A stale typed resume cannot be consumed by a later clarification gate."""
    continuation = ClarificationContinuation(
        request_id="clarify-old", prompt="Take a different approach."
    )

    with pytest.raises(ValueError, match="does not match"):
        parse_clarification_resolution(
            continuation.as_resume_value(), request_id="clarify-current"
        )

    stale_decline = ClarificationDecline(request_id="clarify-old")
    with pytest.raises(ValueError, match="does not match"):
        parse_clarification_resolution(
            stale_decline.as_resume_value(), request_id="clarify-current"
        )

    with pytest.raises(ValueError, match="discriminator"):
        parse_clarification_resolution(
            {
                "type": "document_approval_request",
                "request_id": "clarify-current",
            },
            request_id="clarify-current",
        )


def test_resolution_fingerprint_is_canonical_and_outcome_sensitive() -> None:
    """Answer insertion order is noise, while resolution content is identity."""
    first = ClarificationAnswers(
        request_id="clarify-1",
        answers={"scope": "backend", "constraints": "keep it small"},
    )
    reordered = ClarificationAnswers(
        request_id="clarify-1",
        answers={"constraints": "keep it small", "scope": "backend"},
    )
    changed_answer = ClarificationAnswers(
        request_id="clarify-1",
        answers={"scope": "frontend", "constraints": "keep it small"},
    )
    continuation = ClarificationContinuation(
        request_id="clarify-1", prompt="Discuss the trade-off first."
    )
    decline = ClarificationDecline(request_id="clarify-1")

    fingerprint = clarification_resolution_fingerprint(first)
    assert fingerprint.startswith("sha256:")
    assert fingerprint == clarification_resolution_fingerprint(reordered)
    assert fingerprint != clarification_resolution_fingerprint(changed_answer)
    assert fingerprint != clarification_resolution_fingerprint(continuation)
    assert clarification_resolution_fingerprint(decline) not in {
        fingerprint,
        clarification_resolution_fingerprint(continuation),
    }


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
    # Passed via dict-unpacking rather than a literal kwarg: "hint" is not a
    # field on ClarificationQuestion, and the point of this test is that the
    # model's extra="forbid" config rejects it at construction time anyway.
    smuggled: dict[str, Any] = {
        "id": "scope",
        "prompt": "Which?",
        "kind": ClarificationKind.TEXT,
        "hint": "smuggled",
    }
    with pytest.raises(ValidationError):
        ClarificationQuestion(**smuggled)


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
