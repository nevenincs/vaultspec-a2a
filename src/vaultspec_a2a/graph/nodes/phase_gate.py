"""Generalized per-phase human-approval gate.

The phase gate generalizes the plan-approval pattern
(``create_plan_approval_node``) from a single execution gate into a factory
parameterized by document phase. The gate is split into two nodes so the
correlation ids are COMMITTED to the checkpoint before the run parks:

- The submit node (:func:`create_phase_submit_node`) is the deterministic
  pre-interrupt side effect: a propose-and-submit through an injected
  :class:`DocumentProposalSubmitter`, returning the ``proposal_id`` and
  ``gate_phase`` into state and routing on into the gate node. Because it commits
  as its own superstep, the proposal id is durable in the checkpoint WHILE the
  run is parked - the run-external verdict subscriber correlates a verdict to the
  parked run through those committed ids. A single-node gate would instead
  write the ids only in its post-resume return, so nothing would correlate
  while parked. The submit is replay-safe: the authoring client derives idempotency
  keys from stable run-local material, so should the checkpoint not commit and
  the node re-run, the repeated submit is a deduplicated no-op returning the same
  proposal id.
- The gate node (:func:`create_phase_gate_node`) is pure: its only act is the
  ``interrupt()`` on the parked verdict plus the verdict routing. A resumed run
  restarts at this node, so the submit node does NOT re-run on resume.

The submitter is a Protocol seam, not a concrete client: the control layer owns
wiring the real authoring client (out of this module's scope), so the gate stays
decoupled from the authoring package and independently testable.

Wire contract (distinct from the plan-approval gate, whose payload is
unchanged): the interrupt payload is
``{"type": "document_approval_request", "phase", "proposal_id", "feature",
"request_id"}`` and the resume payload is a
:class:`~vaultspec_a2a.thread.resume_values.ApprovalVerdict` naming the
proposal. An ``approved`` verdict advances to the next stage; ``rejected`` and
``request_changes`` route to the phase's writer with the reviewer notes appended
to ``validation_errors`` so the writer has a concrete revise signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from langgraph.types import Command

from ...thread.enums import (
    VERDICT_APPROVED,
    VERDICT_REJECTED,
    VERDICT_REQUEST_CHANGES,
    InterruptType,
)
from ...thread.errors import DocumentConformanceError
from ...thread.resume_values import parse_approval_verdict
from ._interrupts import await_request_scoped_resume

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...thread.state import TeamState
    from .worker import RoutingNode

# The verdict vocabulary is imported to ROUTE ON, not to offer a second way in:
# thread.enums holds it precisely because this module and the authoring lifecycle
# cannot import each other, and a consumer taking it from either would undo that.
__all__ = [
    "REVIEW_REVISION_SENTINEL",
    "DocumentProposalSubmitter",
    "ProposalRevisionRequiredError",
    "create_phase_gate_node",
    "create_phase_submit_node",
    "review_requests_revision",
    "review_revisions_spent",
    "revision_granted",
]

#: The standalone verdict line a reviewer persona emits to send work back.
REVIEW_REVISION_SENTINEL = "REVISION REQUIRED"


def review_requests_revision(messages: Sequence[object]) -> bool:
    """Whether the latest message is a reviewer verdict asking for revision.

    An anchored whole-line match, not a substring, so reviewer prose such as
    "no revision required" never reads as a request. Anything else - the
    ``PASS`` verdict, or no verdict at all - is not a request.
    """
    if not messages:
        return False
    content = str(getattr(messages[-1], "content", ""))
    return REVIEW_REVISION_SENTINEL in {
        line.strip().upper() for line in content.splitlines()
    }


def revision_granted(*, revision_requested: bool, spent: int, budget: int) -> bool:
    """Whether a review loop sends its work back to the writer once more.

    The one budget rule every review loop applies: a revision is granted only
    when one is asked for and the revisions ``spent`` - counting the one being
    asked for - stay within ``budget``. A reviewer that never passes would
    otherwise loop until the recursion limit killed the run, so a spent budget
    ends the loop whatever the verdict says.
    """
    return revision_requested and spent <= budget


def review_revisions_spent(state: TeamState, phase: str) -> int:
    """The revisions ``phase`` has spent since it last reached its gate."""
    return (state.get("review_revisions") or {}).get(phase, 0)


_REVISION_VERDICTS = frozenset({VERDICT_REJECTED, VERDICT_REQUEST_CHANGES})


class ProposalRevisionRequiredError(Exception):
    """A submitter refusal that must route back to the writer, not fail the run.

    Part of the :class:`DocumentProposalSubmitter` seam contract: a submitter
    raises this (or a subclass) BEFORE proposing when the writer's body fails a
    vault conformance rule the engine would reject at materialization. It carries
    one actionable note per violation in :attr:`revision_notes`; the submit node
    routes those into the phase's inner revision loop as the writer's revise
    signal. Defined here (with the Protocol) so the gate catches the refusal
    without importing the concrete authoring package.
    """

    def __init__(self, revision_notes: list[str]) -> None:
        self.revision_notes = revision_notes
        super().__init__("; ".join(revision_notes))


class DocumentProposalSubmitter(Protocol):
    """Deterministic, idempotent propose-and-submit for a document phase.

    Called before the gate's ``interrupt()`` on every pass, including the replay
    on resume. Implementations MUST be idempotent: a second call for the same run
    and phase is a no-op replay returning the same proposal id, so the gate is
    replay-safe. The concrete implementation wraps the engine authoring client
    and is injected by the control layer.
    """

    async def __call__(self, state: TeamState, phase: str) -> str:
        """Propose and submit the phase's document; return its proposal id."""
        ...


def create_phase_submit_node(
    phase: str,
    submitter: DocumentProposalSubmitter,
    *,
    gate_target: str,
    revision_target: str,
    max_revisions: int,
) -> RoutingNode:
    """Create the deterministic pre-interrupt propose-and-submit node.

    Runs the idempotent submitter and COMMITS the resulting correlation ids into
    state before routing into the gate node. Because this runs as its own
    superstep, ``authoring_proposal_ids`` and ``gate_phase`` are durable in the
    checkpoint while the downstream gate node is parked at its interrupt - the
    verdict subscriber needs those committed ids to correlate an out-of-run
    verdict to the parked run.

    Conformance backstop: the submitter refuses a body that would fail vault
    conformance at materialization (leftover template annotations/placeholders, a
    wiki-/markdown-link in body prose, or a document that does not begin at its
    frontmatter fence) by raising an exception carrying non-empty
    ``revision_notes``. Rather than fail the run, this node routes that back into
    the phase's inner revision loop as REVISION REQUIRED with the notes appended to
    ``validation_errors`` - the SAME concrete revise signal the gate node emits on a
    human ``request_changes`` - so the writer gets a targeted second chance and a
    malformed body never reaches the gate or apply. Detection is by the
    ``revision_notes`` attribute (a duck-typed contract), so the gate module stays
    decoupled from the authoring package.

    That second chance is BUDGETED, on the same per-phase counter the inner
    review loop spends: both are revisions of this phase's document by the same
    writer, and a refusal that cost nothing looped writer -> review -> submit
    until the recursion limit killed the run. A spent budget raises
    :class:`...thread.errors.DocumentConformanceError` rather than parking at
    the human gate, because a refusal happens BEFORE any proposal exists: the
    gate's payload would name no proposal and the out-of-run verdict subscriber
    correlates a verdict by exactly that id, so a park here is a pause nothing
    could end.

    Args:
        phase:           The document phase this gate guards (e.g. ``research``,
                         ``adr``); recorded in ``gate_phase`` and carried to the gate.
        submitter:       Deterministic, idempotent propose-and-submit callable;
                         returns the proposal id.
        gate_target:     The pure gate node to route into after the submit commits.
        revision_target: The phase's writer, routed to when the submitter refuses a
                         non-conformant body (the SAME target the gate uses on
                         ``request_changes``).
        max_revisions:   The phase's revision budget, shared with the inner review
                         loop's router so the two cannot each spend it in full.

    Returns:
        An async node that proposes+submits and routes via ``Command.goto`` into
        the gate, committing ``authoring_proposal_ids`` / ``gate_phase`` /
        ``gate_pending_proposal_id`` - or, on a conformance refusal within budget,
        routes to the writer with the specific check notes.

    Raises:
        DocumentConformanceError: The submitter refused and the phase has no
            revision left to spend.
    """

    async def phase_submit_node(state: TeamState) -> Command[Any]:
        """Propose+submit (idempotent), commit the ids, route into the gate."""
        try:
            proposal_id = await submitter(state, phase)
        except ProposalRevisionRequiredError as exc:
            spent = review_revisions_spent(state, phase)
            # The refusal is weighed before it is counted, so even a zero
            # budget grants the writer one corrective pass.
            if not revision_granted(
                revision_requested=True, spent=spent, budget=max_revisions
            ):
                raise DocumentConformanceError(
                    phase, exc.revision_notes, attempts=spent
                ) from exc
            return Command(
                goto=revision_target,
                update={
                    "next": revision_target,
                    "gate_phase": phase,
                    "gate_verdict": VERDICT_REQUEST_CHANGES,
                    "validation_errors": list(exc.revision_notes),
                    "review_revisions": {phase: spent + 1},
                },
            )
        return Command(
            goto=gate_target,
            update={
                "next": gate_target,
                "gate_phase": phase,
                "gate_pending_proposal_id": proposal_id,
                "authoring_proposal_ids": [proposal_id],
                "routing_error": None,
                # A revision the human asks for at the gate gets a fresh budget.
                "review_revisions": {phase: 0},
            },
        )

    phase_submit_node.__name__ = f"phase_submit_{phase}"
    return phase_submit_node


def create_phase_gate_node(
    phase: str,
    *,
    approved_target: str,
    revision_target: str,
) -> RoutingNode:
    """Create the pure per-phase document-approval gate node.

    The proposal was submitted and its id committed to state by the preceding
    :func:`create_phase_submit_node`; this node's only act is the ``interrupt()``
    on the parked verdict and the verdict routing. A resumed run restarts at this
    node (the submit node already committed), so nothing re-submits on resume.

    Args:
        phase:           The document phase this gate guards; carried in the
                         interrupt payload and recorded in ``gate_phase``.
        approved_target: Node to route to when the reviewer approves.
        revision_target: Node to route to on ``rejected`` / ``request_changes``
                         (the phase's writer); reviewer notes are appended to
                         ``validation_errors``.

    Returns:
        An async node that interrupts for the human verdict and on resume routes
        via ``Command.goto`` with the verdict recorded in ``gate_verdict``.
    """

    async def phase_gate_node(state: TeamState) -> Command[Any]:
        """Pause for the committed proposal's verdict, then route."""
        proposal_id = state.get("gate_pending_proposal_id")
        payload = {
            "type": InterruptType.DOCUMENT_APPROVAL_REQUEST.value,
            "phase": phase,
            "proposal_id": proposal_id,
            "feature": state.get("active_feature"),
            # The proposal this gate parked on IS its request identity: it is
            # committed to the checkpoint before the park and it is what the
            # out-of-run verdict subscriber correlates a decision by.
            "request_id": proposal_id,
        }
        if not proposal_id:
            # With no committed proposal the gate has no request id to put in
            # its payload, and a verdict counts here only when it names this
            # gate's request, so a park could only ever end in a rejection.
            # The gate takes that rejection now and the writer resubmits,
            # rather than pausing the run for an answer that cannot count.
            verdict, notes = (
                VERDICT_REJECTED,
                f"Document phase {phase!r} reached its gate with no committed "
                "proposal; resubmit it before a decision can be asked for.",
            )
        else:
            # An answer bound to another request, or to none, is not this
            # gate's decision, so the gate asks again rather than spending a
            # revision on it. The decision stays the human's, and the phase's
            # revision budget is spent only by a verdict a human gave on this
            # document.
            decision = await_request_scoped_resume(
                payload, proposal_id, parse_approval_verdict
            )
            verdict, notes = decision.verdict, decision.notes

        if verdict == VERDICT_APPROVED:
            return Command(
                goto=approved_target,
                update={
                    "next": approved_target,
                    "gate_phase": phase,
                    "gate_verdict": VERDICT_APPROVED,
                    "routing_error": None,
                    # The phase advances, so its revision notes stop being
                    # active errors. Nothing else clears them, and anchoring
                    # shows every active error to every later worker: an ADR
                    # author was still being told to "fix sources" about a
                    # research document the human had since approved. The empty
                    # list is the channel's own clear signal.
                    "validation_errors": [],
                },
            )

        # Rejected / request_changes (and any unrecognised verdict, which fails
        # closed to revision rather than silently advancing): route to the
        # phase's writer with the reviewer's notes as a concrete revise signal.
        recorded_verdict = (
            verdict if verdict in _REVISION_VERDICTS else VERDICT_REJECTED
        )
        revise_note = notes or (
            f"Document phase {phase!r} was not approved "
            f"(verdict: {recorded_verdict}); revise before resubmitting."
        )
        return Command(
            goto=revision_target,
            update={
                "next": revision_target,
                "gate_phase": phase,
                "gate_verdict": recorded_verdict,
                "validation_errors": [revise_note],
            },
        )

    phase_gate_node.__name__ = f"phase_gate_{phase}"
    return phase_gate_node
