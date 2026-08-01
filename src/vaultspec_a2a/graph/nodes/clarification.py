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
  answers. Because the resume restarts here, the producer is NOT consulted twice
  and the question a human sees after a reload is byte-identical to the one they
  saw before it.

Committing before parking is also what makes the question READABLE while the run
is parked: the interrupt payload sits in the checkpoint, which is exactly where
the recovery snapshot reads it from.

Wire contract: the interrupt payload is a
:class:`~vaultspec_a2a.thread.clarification.ClarificationRequest` rendered as
JSON (``{"type": "clarification_request", "request_id", "questions": [...]}``)
and the resume payload is a
:class:`~vaultspec_a2a.thread.clarification.ClarificationAnswers`
(``{"type": "clarification_response", "request_id", "answers": {question_id:
answer}}``). Both shapes, and every bound on them, are owned by
:mod:`vaultspec_a2a.thread.clarification` so the node, the wire, and the
snapshot cannot disagree about what was asked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from langgraph.types import Command, interrupt

from ...thread.clarification import ClarificationRequest

if TYPE_CHECKING:
    from ...thread.state import TeamState
    from .worker import WorkerNode

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


def _parse_answers(
    resume_value: object,
    request: ClarificationRequest,
) -> dict[str, str]:
    """Extract the answers a resume carries, keyed by declared question id.

    Defensive rather than authoritative: the answering verb validates a
    questionnaire at the boundary, so this only guards against a resume that
    never went through it. An entry whose key is not a declared question, or
    whose value is not a string, is dropped - it could not be routed to a
    question anyway - and everything else is taken as given.
    """
    if not isinstance(resume_value, dict):
        return {}
    raw = resume_value.get("answers")
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str)
        and isinstance(value, str)
        and request.question(key) is not None
    }


def create_clarification_request_node(
    producer: ClarificationQuestionProducer,
    *,
    gate_target: str,
    proceed_target: str,
) -> WorkerNode:
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

    async def clarification_request_node(state: TeamState) -> Command:
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


def create_clarification_gate_node(*, proceed_target: str) -> WorkerNode:
    """Create the pure "park on the question, record the answers" node.

    Its only acts are the ``interrupt()`` on the committed question set and the
    recording of the answers the resume carries. Nothing is produced here, so a
    resumed run replays this node alone and the human sees the same question set
    it was shown before any restart.

    An unreadable or absent committed request routes on rather than parking: a
    run must not be stranded at an interrupt whose question nobody can render.

    Args:
        proceed_target: The stage the run continues to once answered.

    Returns:
        An async node that interrupts for the answers and on resume routes via
        ``Command.goto`` with the answers recorded under their request id and the
        pending question cleared.
    """

    async def clarification_gate_node(state: TeamState) -> Command:
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

        resume_value = interrupt(request.as_interrupt_payload())
        answers = _parse_answers(resume_value, request)
        recorded_answers = state.get("clarification_answers")
        all_answers = (
            dict(recorded_answers) if isinstance(recorded_answers, dict) else {}
        )
        all_answers[request.request_id] = answers

        update: dict[str, Any] = {
            "next": proceed_target,
            # The question is answered; clearing it is what makes a later
            # status read report "not waiting" rather than re-offering a
            # questionnaire the human already filled in.
            "clarification_request": None,
            "clarification_request_id": None,
            "clarification_answers": all_answers,
        }
        return Command(goto=proceed_target, update=update)

    clarification_gate_node.__name__ = "clarification_gate"
    return clarification_gate_node
