"""Mid-run clarification interrupt node (agent-flow ADR D5).

A reusable primitive, the sibling of the phase gate
(:mod:`vaultspec_a2a.graph.nodes.phase_gate`): a node that pauses the run on
a checkpointed ``interrupt()`` and resumes on a typed answer. Where the phase
gate asks one fixed-option question (approve/reject/request_changes), this
node asks the RUN's own question set — a bounded list of structured
questions a caller (a Ground or Diverge stage worker) placed in state before
routing here.

Wire contract: the interrupt payload is
``{"type": "clarification_request", "questions": [{"id", "prompt", "kind":
"choice"|"text", "options"?, "required"}, ...]}`` (capped: at most
``MAX_CLARIFICATION_QUESTIONS`` questions, at most ``MAX_QUESTION_OPTIONS``
options per choice question, every string field bounded and forced
single-line); the resume payload is a flat ``{question_id: answer}`` map.
Bounding is by truncation, not refusal — mirroring the SSE frame catalog's
projection-by-omission discipline — so a caller that proposes an
over-generous question set degrades to the capped one rather than crashing
the run.

This node does not decide WHEN to ask a question or WHAT to ask; it is the
pause/resume mechanism only. A caller populates ``clarification_questions``
in state before routing here (or the node is a no-op passthrough when no
questions are pending), and reads ``clarification_answers`` after resume.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

from langgraph.types import interrupt

if TYPE_CHECKING:
    from ...thread.state import TeamState
    from .worker import WorkerNode

__all__ = [
    "CLARIFICATION_ANSWER_KINDS",
    "MAX_ANSWER_CHARS",
    "MAX_CLARIFICATION_QUESTIONS",
    "MAX_QUESTION_ID_CHARS",
    "MAX_QUESTION_OPTIONS",
    "MAX_QUESTION_OPTION_CHARS",
    "MAX_QUESTION_PROMPT_CHARS",
    "bound_clarification_questions",
    "create_clarification_node",
]

#: Caps from agent-flow ADR D5: "≤4 questions per request, ≤4 options per
#: choice, capped strings".
MAX_CLARIFICATION_QUESTIONS = 4
MAX_QUESTION_OPTIONS = 4
MAX_QUESTION_ID_CHARS = 64
MAX_QUESTION_PROMPT_CHARS = 512
MAX_QUESTION_OPTION_CHARS = 128

#: The engine caps an answer value at 4096 chars and rejects multiline
#: (control characters); this node enforces the same bound and single-line
#: discipline on the a2a side of the same field, so a payload this node
#: accepts is never refused downstream for a shape it could have caught here.
MAX_ANSWER_CHARS = 4096

CLARIFICATION_ANSWER_KINDS: frozenset[str] = frozenset({"choice", "text"})

#: The token grammar the engine's `/v1/runs/{run_id}/clarifications/
#: {request_id}/respond` boundary validates answer keys (question ids)
#: against: alphanumeric plus ``_ - . :``, capped at 64 chars, and — matching
#: the engine's ``bounded_token_is_valid`` — never STARTING with a hyphen (a
#: leading ``-`` elsewhere reads as a CLI flag marker in several downstream
#: consumers). Enforced HERE, at minting, so a question id this node ever
#: advertises is always answerable through that boundary — a caller proposing
#: e.g. a space, a leading hyphen, or a unicode id degrades to having that
#: question dropped rather than parking a run unanswerable through the
#: dashboard.
_QUESTION_ID_GRAMMAR = re.compile(r"^[A-Za-z0-9_.:][A-Za-z0-9_.:-]{0,63}$")


def _single_line(text: str) -> str:
    """Collapse any control/newline character out of *text*.

    Neither questions nor answers may carry a newline or other control
    character — the engine rejects a multiline answer outright, and this
    keeps a question prompt/option from smuggling one through either.
    """
    return "".join(ch for ch in text if ch == "\t" or ch >= " ")


def _bounded_text(value: object, max_chars: int) -> str:
    text = value if isinstance(value, str) else str(value)
    return _single_line(text)[:max_chars]


def bound_clarification_questions(
    questions: list[Any],
) -> list[dict[str, Any]]:
    """Cap a proposed question list to the D5 bounds; truncate, never raise.

    A malformed or oversized question list degrades to its capped, valid
    subset rather than failing the run: any non-dict entry, or any entry
    missing a non-empty ``id``/``prompt``, is dropped; an ``id`` that does not
    match the engine's answer-key token grammar (``_QUESTION_ID_GRAMMAR``) is
    dropped rather than advertised unanswerable; a ``choice`` question's
    options list is capped and empty/duplicate option text is dropped.

    Filter THEN cap, not the reverse: the ``MAX_CLARIFICATION_QUESTIONS``
    limit applies to the VALID result, not the raw input window, so malformed
    leading entries can never push valid ones out of the cap (a 6-entry list
    with 2 malformed leaders still yields the 4 valid trailing questions, not
    2).
    """
    bounded: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in questions:
        if len(bounded) >= MAX_CLARIFICATION_QUESTIONS:
            break
        if not isinstance(raw, dict):
            continue
        qid = _bounded_text(raw.get("id", ""), MAX_QUESTION_ID_CHARS)
        prompt = _bounded_text(raw.get("prompt", ""), MAX_QUESTION_PROMPT_CHARS)
        if (
            not qid
            or not prompt
            or qid in seen_ids
            or not _QUESTION_ID_GRAMMAR.match(qid)
        ):
            continue
        kind = raw.get("kind")
        kind = kind if kind in CLARIFICATION_ANSWER_KINDS else "text"
        question: dict[str, Any] = {
            "id": qid,
            "prompt": prompt,
            "kind": kind,
            "required": bool(raw.get("required", False)),
        }
        if kind == "choice":
            raw_options = raw.get("options", [])
            options: list[str] = []
            if isinstance(raw_options, list):
                for opt in raw_options[:MAX_QUESTION_OPTIONS]:
                    text = _bounded_text(opt, MAX_QUESTION_OPTION_CHARS)
                    if text and text not in options:
                        options.append(text)
            question["options"] = options
        bounded.append(question)
        seen_ids.add(qid)
    return bounded


def create_clarification_node(
    *,
    questions_field: str = "clarification_questions",
    answers_field: str = "clarification_answers",
    name: str = "clarification",
) -> WorkerNode:
    """Create the reusable mid-run clarification interrupt node.

    Reads a bounded question list from ``state[questions_field]`` (populated
    by a preceding Ground/Diverge-stage node), bounds it to the D5 caps, and —
    when non-empty — raises ``interrupt()`` with the typed payload. On resume,
    the answer map is recorded into ``state[answers_field]`` (every value
    coerced to a bounded, single-line string) and the node returns normally,
    letting the caller's static edges route onward.

    When the question list is empty (no clarification needed this pass), the
    node is a no-op passthrough — no interrupt, no state change — so it can
    sit unconditionally on an edge without forcing every run through a pause.

    A resumed run re-executes this node from its start (LangGraph interrupt
    semantics), so the question-bounding above the ``interrupt()`` call is
    pure and side-effect free. The one value that is NOT reproduced
    identically across a replay is the generated ``request_id`` (below) — this
    is deliberately safe: a resume already carries an answer for the SAME
    task, so ``interrupt()`` returns it immediately without re-pausing, and
    the freshly (re)computed payload passed to it on that replay is never
    checkpointed. The id that matters — the one disclosed on ``run-status``
    and used in the respond route's path — is whatever was live at the
    ORIGINAL park, frozen in the checkpoint from that point on.
    """

    async def clarification_node(state: TeamState) -> dict[str, Any]:
        """Pause for the run's clarification questions, then record answers."""
        raw_questions = state.get(questions_field) or []
        questions = bound_clarification_questions(list(raw_questions))
        if not questions:
            return {}
        # Path-safe by construction (lowercase hex), unlike the checkpoint-
        # derived interrupt-id fallback (thread/snapshots.py), which contains
        # colons and would fail the respond route's path pattern.
        request_id = uuid.uuid4().hex[:16]
        resume_value = interrupt(
            {
                "type": "clarification_request",
                "request_id": request_id,
                "questions": questions,
            }
        )
        answers = resume_value if isinstance(resume_value, dict) else {}
        bounded_answers = {
            str(key): _bounded_text(value, MAX_ANSWER_CHARS)
            for key, value in answers.items()
            if isinstance(key, str)
        }
        return {answers_field: bounded_answers}

    clarification_node.__name__ = name
    return clarification_node
