"""The typed, bounded mid-run clarification contract.

A run that needs a structured answer from the human pauses on a checkpointed
LangGraph ``interrupt()`` carrying a *clarification request*, and resumes only
through the typed ``Command(resume=...)`` that answers it. This module owns the
shape of both halves, and owns them once: the graph node builds its interrupt
payload from these models, the gateway validates an inbound answer against them,
and the recovery snapshot re-reads a parked question through them. A second
declaration of the same shape at any of those layers is what lets a question the
graph asked and a question the wire renders drift apart.

Bounds are the contract, not advice, so they live in the type system rather than
in prose: at most :data:`MAX_QUESTIONS_PER_REQUEST` questions per request, at most
:data:`MAX_OPTIONS_PER_QUESTION` options per choice, and every string capped. A
producer that exceeds a bound fails construction where it is written, not silently
at the wire.

Two rules shape the design beyond the bounds:

- **The checkpoint is the authority.** A parked question is read back out of the
  run's own checkpoint (:func:`pending_clarification`), never out of a relay
  frame or a side table. Recovery after a reload therefore re-renders the
  questionnaire from the same bytes the graph is parked on, and a lost progress
  frame costs nothing.
- **Parsing is lenient, construction is strict.**
  :meth:`ClarificationRequest.from_payload`
  answers ``None`` for anything it cannot read as a well-formed request, because
  its input is a checkpoint written by some earlier version of this code and a
  malformed one must degrade to "no pending question" rather than fail a
  status read. Direct construction, by contrast, refuses every violation.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .snapshots import project_checkpoint_tuple

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CLARIFICATION_INTERRUPT_TYPE",
    "CLARIFICATION_RESUME_TYPE",
    "CLARIFICATION_TOPOLOGIES",
    "MAX_ANSWER_CHARS",
    "MAX_OPTIONS_PER_QUESTION",
    "MAX_OPTION_CHARS",
    "MAX_PROMPT_CHARS",
    "MAX_QUESTIONS_PER_REQUEST",
    "ClarificationAnswers",
    "ClarificationKind",
    "ClarificationQuestion",
    "ClarificationRequest",
    "pending_clarification",
    "topology_honours_clarification",
    "validate_clarification_answers",
]

# The interrupt discriminator the parked node raises, and the discriminator the
# answering resume carries back. Both are matched by string at the checkpoint and
# dispatch boundaries, so they are named once here.
CLARIFICATION_INTERRUPT_TYPE = "clarification_request"
CLARIFICATION_RESUME_TYPE = "clarification_response"

# The topologies whose compiled graph actually MOUNTS the clarification stage,
# named once so the layer that accepts a declaration and the layer that honours it
# cannot disagree. Membership is a promise about the graph builder, not a label: a
# topology named here mounts the request and gate nodes in ``graph.compiler``, and
# a topology absent from it refuses a ``[team.clarification]`` declaration outright
# at preset load and again at compile. Refusing is the point - a declaration
# accepted by a topology that never asks is a run that silently skips its own
# questionnaire, which is indistinguishable from a working run until a human
# notices they were never asked.
#
# Topology-type STRING values: ``TopologyType`` is a ``StrEnum``, so a member
# equals and hashes as its ``str`` value and callers pass enum members directly.
CLARIFICATION_TOPOLOGIES: frozenset[str] = frozenset({"research_adr"})


def topology_honours_clarification(topology_type: str) -> bool:
    """Return whether a graph of *topology_type* mounts the clarification stage.

    Accepts a ``TopologyType`` member directly (``StrEnum``), so no stringification
    is needed at call sites.
    """
    return topology_type in CLARIFICATION_TOPOLOGIES


# Cardinality bounds. A questionnaire is a bounded interruption of a run, not a
# form: four questions is the ceiling a human answers without abandoning the run,
# and four options is the ceiling a choice renders as buttons.
MAX_QUESTIONS_PER_REQUEST = 4
MAX_OPTIONS_PER_QUESTION = 4

# String bounds. Sized so a whole request stays small enough to sit inside a
# checkpoint and inside the status response without special handling.
MAX_IDENTIFIER_CHARS = 64
MAX_REQUEST_ID_CHARS = 128
MAX_PROMPT_CHARS = 512
MAX_OPTION_CHARS = 128
MAX_ANSWER_CHARS = 2048

# Question and request identifiers are correlation handles that travel in a URL
# path and in JSON object keys, so they are restricted to a path- and key-safe
# alphabet rather than merely capped.
_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$"

QuestionId = Annotated[
    str,
    Field(min_length=1, max_length=MAX_IDENTIFIER_CHARS, pattern=_IDENTIFIER_PATTERN),
]
ClarificationRequestId = Annotated[
    str,
    Field(min_length=1, max_length=MAX_REQUEST_ID_CHARS, pattern=_IDENTIFIER_PATTERN),
]
OptionLabel = Annotated[str, Field(min_length=1, max_length=MAX_OPTION_CHARS)]
AnswerText = Annotated[str, Field(max_length=MAX_ANSWER_CHARS)]


class ClarificationKind(StrEnum):
    """How one question is answered.

    ``choice`` offers a bounded set of declared options and admits exactly one of
    them verbatim as its answer; ``text`` admits free prose up to
    :data:`MAX_ANSWER_CHARS`. The two exhaust the vocabulary: a kind the renderer
    does not know is a question it cannot render, so the set is closed.
    """

    CHOICE = "choice"
    TEXT = "text"


class ClarificationQuestion(BaseModel):
    """One bounded question inside a clarification request.

    ``options`` belongs to ``choice`` and only to ``choice``: a text question
    carrying options would advertise a constraint the answer path does not
    enforce, and a choice without options would offer nothing to choose. Both are
    refused at construction rather than tolerated and interpreted downstream.
    """

    model_config = ConfigDict(extra="forbid")

    id: QuestionId
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    kind: ClarificationKind
    options: list[OptionLabel] | None = Field(
        default=None, max_length=MAX_OPTIONS_PER_QUESTION
    )
    required: bool = True

    @model_validator(mode="after")
    def _options_match_kind(self) -> Self:
        """Bind the option list to the kind that gives it meaning."""
        if self.kind is ClarificationKind.CHOICE:
            if not self.options:
                msg = f"choice question {self.id!r} declares no options"
                raise ValueError(msg)
            if len(set(self.options)) != len(self.options):
                msg = f"choice question {self.id!r} declares duplicate options"
                raise ValueError(msg)
        elif self.options is not None:
            msg = f"text question {self.id!r} must not declare options"
            raise ValueError(msg)
        return self


class ClarificationRequest(BaseModel):
    """The bounded question set a parked run is waiting on.

    This is the interrupt payload verbatim: what the node raises, what the
    checkpoint holds while the run is parked, and what the recovery snapshot
    discloses. ``type`` is carried rather than implied because the checkpoint
    holds interrupts of several kinds side by side and the discriminator is how a
    reader tells a clarification from an approval.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["clarification_request"] = CLARIFICATION_INTERRUPT_TYPE
    request_id: ClarificationRequestId
    questions: list[ClarificationQuestion] = Field(
        min_length=1, max_length=MAX_QUESTIONS_PER_REQUEST
    )

    @model_validator(mode="after")
    def _unique_question_ids(self) -> Self:
        """Keep question ids unique - answers are keyed by them."""
        ids = [question.id for question in self.questions]
        if len(set(ids)) != len(ids):
            msg = "clarification questions must have unique ids"
            raise ValueError(msg)
        return self

    def as_interrupt_payload(self) -> dict[str, Any]:
        """Render the request as the JSON-safe payload handed to ``interrupt()``.

        The checkpointer persists plain JSON, so the model is flattened here
        rather than at each call site - a model instance reaching the checkpoint
        would not survive a reload.
        """
        return self.model_dump(mode="json")

    @classmethod
    def from_payload(cls, payload: object) -> ClarificationRequest | None:
        """Read a request back out of a persisted interrupt payload, or ``None``.

        Lenient by design: the input is a checkpoint this process did not
        necessarily write, so anything that is not a well-formed clarification
        request - a different interrupt kind, a truncated payload, a shape from a
        future producer - reads as "no pending clarification" instead of failing
        the status read that called it.
        """
        if not isinstance(payload, dict):
            return None
        if payload.get("type") != CLARIFICATION_INTERRUPT_TYPE:
            return None
        try:
            return cls.model_validate(payload)
        except ValueError:
            return None

    def question(self, question_id: str) -> ClarificationQuestion | None:
        """Return the question with *question_id*, or ``None``."""
        for question in self.questions:
            if question.id == question_id:
                return question
        return None


class ClarificationAnswers(BaseModel):
    """The typed resume payload that answers a parked clarification.

    Answers are keyed by question id, which is what makes the mapping
    self-describing across a reload: the answering client need not have seen the
    request in the same process, only re-read it from the recovery snapshot.

    The bounds here are structural (how many answers, how long each may be). The
    *semantic* checks that need the request itself - unknown ids, missing required
    answers, a choice outside its declared options - live in
    :func:`validate_clarification_answers`, because a model cannot see the
    question set it is answering.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["clarification_response"] = CLARIFICATION_RESUME_TYPE
    request_id: ClarificationRequestId
    answers: dict[QuestionId, AnswerText] = Field(max_length=MAX_QUESTIONS_PER_REQUEST)

    def as_resume_value(self) -> dict[str, Any]:
        """Render the answers as the JSON-safe value handed to ``Command(resume=)``."""
        return self.model_dump(mode="json")


def validate_clarification_answers(
    request: ClarificationRequest,
    answers: Mapping[str, str],
) -> list[str]:
    """Check *answers* against the question set they claim to answer.

    Returns one note per violation and an empty list when the answers are
    admissible. Reporting every violation at once rather than raising on the
    first keeps a rejected questionnaire answerable in one correction instead of
    one round trip per mistake.

    Four rules, all of which need the request in hand and so cannot be expressed
    on :class:`ClarificationAnswers` alone: every answered id must be a declared
    question, every required question must carry a non-empty answer, a choice
    answer must be one of that question's declared options verbatim, and an
    optional question that IS answered is held to the same option rule as a
    required one.
    """
    notes: list[str] = []
    declared = {question.id for question in request.questions}

    for answered_id in answers:
        if answered_id not in declared:
            notes.append(f"unknown question id {answered_id!r}")

    for question in request.questions:
        answer = answers.get(question.id)
        if answer is None or not answer.strip():
            if question.required:
                notes.append(f"question {question.id!r} is required and unanswered")
            continue
        if question.kind is ClarificationKind.CHOICE:
            options = question.options or []
            if answer not in options:
                notes.append(
                    f"answer to question {question.id!r} is not one of its "
                    f"declared options"
                )
    return notes


def pending_clarification(
    checkpoint_tuple: object | None,
    *,
    thread_id: str,
) -> ClarificationRequest | None:
    """Read the clarification a run is parked on out of its checkpoint.

    The authoritative read behind the recovery disclosure and behind the answer
    path's scoping check. It projects through the shared checkpoint projection
    rather than re-walking ``pending_writes``, so this and the repair surfaces
    agree on what "parked at an interrupt" means.

    Answers ``None`` for a run that is not parked, is parked on a different
    interrupt kind, or has no readable checkpoint at all - each of which is
    honestly "no pending clarification" rather than an error.
    """
    if checkpoint_tuple is None:
        return None
    try:
        projection = project_checkpoint_tuple(checkpoint_tuple, thread_id=thread_id)
    except (AttributeError, TypeError, ValueError):
        return None
    for projected in projection.pending_interrupts:
        if projected.interrupt_type != CLARIFICATION_INTERRUPT_TYPE:
            continue
        request = ClarificationRequest.from_payload(projected.payload)
        if request is not None:
            return request
    return None
