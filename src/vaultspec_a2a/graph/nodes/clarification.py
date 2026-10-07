"""Mid-run clarification: ask the human a bounded, structured question.

The only human-in-the-loop shapes the graph had before this were fixed-option
approvals - allow this tool, approve this plan, accept this document. None of
them can ask "which of these four framings did you mean?" mid-run. This node
pair adds that one primitive, and adds it as a checkpointed ``interrupt()``
rather than as a side channel: a parked question survives a process restart, is
disclosed by the authoritative recovery snapshot, and resumes only through a
typed ``Command(resume=...)``.

Like the document phase gate, the primitive is SPLIT across two nodes, and for
the same reason. A node re-executes from the top when its run resumes -
``interrupt()`` returns the answer on the second pass instead of raising - so a
single node would re-run its pre-interrupt work on every resume. Here that work
is asking a producer (typically a model turn) what to ask, which is neither free
nor guaranteed stable. The split gives:

- The request node (:func:`create_clarification_request_node`) is the
  deterministic pre-interrupt side effect: it calls the producer once and COMMITS
  the resulting question set to the checkpoint as its own superstep. A producer
  that has nothing to ask routes the run straight on, so an autonomous run never
  parks for a question nobody asked.
- The gate node (:func:`create_clarification_gate_node`) is pure: it re-reads the
  committed question set, raises the ``interrupt()``, and on resume records the
  answers or appends the submitted continuation prompt. Because the resume
  restarts here, the producer is NOT consulted twice and the question a human
  sees after a reload is byte-identical to the one they saw before it.

Committing before parking is also what makes the question READABLE while the run
is parked: the interrupt payload sits in the checkpoint, which is exactly where
the recovery snapshot reads it from.

Wire contract: the interrupt payload is a
:class:`~vaultspec_a2a.thread.clarification.ClarificationRequest` rendered as
JSON (``{"type": "clarification_request", "request_id", "questions": [...]}``)
and the resume payload is a
:class:`~vaultspec_a2a.thread.clarification.ClarificationAnswers`, a
:class:`~vaultspec_a2a.thread.clarification.ClarificationContinuation`, or a
:class:`~vaultspec_a2a.thread.clarification.ClarificationDecline`. These
shapes, and every bound on them, are owned by
:mod:`vaultspec_a2a.thread.clarification` so the node, the wire, and the
snapshot cannot disagree about what was asked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from ...thread.clarification import (
    CLARIFICATION_DECLINE_MARKER,
    ClarificationAnswers,
    ClarificationDecline,
    ClarificationRequest,
    clarification_resolution_fingerprint,
    parse_clarification_resolution,
    render_clarification_answers,
)
from ...thread.snapshots import stamp_message_created_at
from ._interrupts import await_request_scoped_resume

if TYPE_CHECKING:
    from ...thread.state import TeamState
    from .worker import RoutingNode

__all__ = [
    "ClarificationQuestionProducer",
    "create_clarification_gate_node",
    "create_clarification_request_node",
]


class ClarificationQuestionProducer(Protocol):
    """Decide what - if anything - to ask the human at this point in the run.

    A Protocol seam rather than a concrete implementation, matching the proposal
    submitter the phase gates take: what a run should ask depends on the stage,
    the persona, and the workspace, none of which this module should know. The
    control layer injects the concrete producer.

    Returning ``None`` is a first-class answer meaning "nothing needs asking" -
    it is how an autonomous run passes through the stage without parking, so a
    producer must never manufacture a question to satisfy the signature.

    Called exactly once per pass through the request node, never on resume.
    """

    async def __call__(self, state: TeamState) -> ClarificationRequest | None:
        """Return the question set to ask, or ``None`` to proceed unasked."""
        ...


def _committed_request(state: TeamState) -> ClarificationRequest | None:
    """Re-read the question set the request node committed, or ``None``."""
    return ClarificationRequest.from_payload(state.get("clarification_request"))


def _declared_answers(
    resolution: ClarificationAnswers,
    request: ClarificationRequest,
) -> dict[str, str]:
    """Keep only answers addressed to questions in the committed request."""
    return {
        key: value
        for key, value in resolution.answers.items()
        if request.question(key) is not None
    }


def create_clarification_request_node(
    producer: ClarificationQuestionProducer,
    *,
    gate_target: str,
    proceed_target: str,
) -> RoutingNode:
    """Create the deterministic pre-interrupt "decide what to ask" node.

    Consults *producer* once and commits its question set to the checkpoint
    before routing into the gate, so the parked run's question is durable and
    readable while it waits. A producer with nothing to ask routes straight to
    *proceed_target* and the run never parks.

    A producer that raises is NOT absorbed. "Ask nothing" already has an explicit
    representation (``None``), so a producer that instead fails is a broken
    producer, and swallowing it here would turn a wiring fault into a run that
    quietly stops asking - the failure mode hardest to notice and hardest to
    diagnose. The node retry policy and the run's own failure path own it.

    Args:
        producer:        Decides the question set for this pass; ``None`` means
                         ask nothing.
        gate_target:     The pure gate node to route into once a question set is
                         committed.
        proceed_target:  The stage the run continues to when there is nothing to
                         ask.

    Returns:
        An async node that routes via ``Command.goto`` into the gate with
        ``clarification_request`` / ``clarification_request_id`` committed, or
        straight on with both cleared.
    """

    async def clarification_request_node(state: TeamState) -> Command[Any]:
        """Decide what to ask, commit it, and route into the gate."""
        request = await producer(state)

        if request is None:
            return Command(
                goto=proceed_target,
                update={
                    "next": proceed_target,
                    "clarification_request": None,
                    "clarification_request_id": None,
                    "routing_error": None,
                },
            )

        return Command(
            goto=gate_target,
            update={
                "next": gate_target,
                "clarification_request": request.as_interrupt_payload(),
                "clarification_request_id": request.request_id,
                "routing_error": None,
            },
        )

    clarification_request_node.__name__ = "clarification_request"
    return clarification_request_node


def create_clarification_gate_node(*, proceed_target: str) -> RoutingNode:
    """Create the pure gate that resolves the committed question request.

    Its only acts are the ``interrupt()`` on the committed question set and the
    typed resolution of the resume it carries. Nothing is produced before the
    interrupt, so a resumed run replays this node alone and the human sees the
    same question set it was shown before any restart.

    An unreadable or absent committed request routes on rather than parking: a
    run must not be stranded at an interrupt whose question nobody can render.

    An answer the request refuses - one bound to another request, or one the
    committed question set cannot accept - parks the run again on the same
    question instead of raising, through
    :func:`._interrupts.await_request_scoped_resume`. The question set stays
    committed, so a status read still discloses the questionnaire the run is
    waiting on.

    Args:
        proceed_target: The stage the run continues to once answered.

    Returns:
        An async node that interrupts and then routes via ``Command.goto`` with
        either an answer reducer delta or one appended human prompt, while the
        pending question is cleared.
    """

    async def clarification_gate_node(state: TeamState) -> Command[Any]:
        """Pause for the committed question set's answers, then route on."""
        request = _committed_request(state)
        if request is None:
            return Command(
                goto=proceed_target,
                update={
                    "next": proceed_target,
                    "clarification_request": None,
                    "clarification_request_id": None,
                },
            )

        resolution = await_request_scoped_resume(
            request.as_interrupt_payload(),
            request.request_id,
            parse_clarification_resolution,
        )

        update: dict[str, Any] = {
            "next": proceed_target,
            # The question is answered; clearing it is what makes a later
            # status read report "not waiting" rather than re-offering a
            # questionnaire the human already filled in.
            "clarification_request": None,
            "clarification_request_id": None,
            "clarification_resolution_receipts": {
                request.request_id: clarification_resolution_fingerprint(resolution)
            },
        }
        if isinstance(resolution, ClarificationAnswers):
            declared = _declared_answers(resolution, request)
            update["clarification_answers"] = {request.request_id: declared}
            # The transcript is the only state downstream turns read, so the
            # answered questionnaire is ALSO rendered as one human turn - the
            # recorded state alone reaches no model. Skipped when nothing was
            # effectively answered (all-optional questionnaire, empty map).
            rendered = render_clarification_answers(request, declared)
            if rendered is not None:
                update["messages"] = [
                    stamp_message_created_at(HumanMessage(content=rendered))
                ]
        elif isinstance(resolution, ClarificationDecline):
            # A decline's whole downstream trace is this one fixed marker: the
            # transcript is the only state model turns read, and without it a
            # declined questionnaire is indistinguishable from one never asked.
            # No answer entry is recorded - refusal is not an answer.
            update["messages"] = [
                stamp_message_created_at(
                    HumanMessage(content=CLARIFICATION_DECLINE_MARKER)
                )
            ]
        else:
            update["messages"] = [
                stamp_message_created_at(HumanMessage(content=resolution.prompt))
            ]
        return Command(goto=proceed_target, update=update)

    clarification_gate_node.__name__ = "clarification_gate"
    return clarification_gate_node
