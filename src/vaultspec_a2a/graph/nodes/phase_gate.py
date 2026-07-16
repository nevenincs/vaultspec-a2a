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

Wire contract (distinct from the plan-approval gate, whose payload and resume
shapes are unchanged): the interrupt payload is
``{"type": "document_approval_request", "phase", "proposal_id", "feature"}`` and
the resume payload is
``{"verdict": "approved" | "rejected" | "request_changes", "notes": str | None}``.
An ``approved`` verdict advances to the next stage; ``rejected`` and
``request_changes`` route to the phase's writer with the reviewer notes appended
to ``validation_errors`` so the writer has a concrete revise signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from langgraph.types import Command, interrupt

if TYPE_CHECKING:
    from vaultspec_a2a.thread.state import TeamState

    from .worker import WorkerNode

__all__ = [
    "VERDICT_APPROVED",
    "VERDICT_REJECTED",
    "VERDICT_REQUEST_CHANGES",
    "DocumentProposalSubmitter",
    "ProposalRevisionRequiredError",
    "create_phase_gate_node",
    "create_phase_submit_node",
]

VERDICT_APPROVED = "approved"
VERDICT_REJECTED = "rejected"
VERDICT_REQUEST_CHANGES = "request_changes"

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


def _parse_verdict(resume_value: object) -> tuple[str | None, str | None]:
    """Extract ``(verdict, notes)`` from a gate resume payload."""
    if not isinstance(resume_value, dict):
        return None, None
    verdict = resume_value.get("verdict")
    notes = resume_value.get("notes")
    verdict_str = verdict if isinstance(verdict, str) else None
    notes_str = notes if isinstance(notes, str) else None
    return verdict_str, notes_str


def create_phase_submit_node(
    phase: str,
    submitter: DocumentProposalSubmitter,
    *,
    gate_target: str,
    revision_target: str,
) -> WorkerNode:
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

    Args:
        phase:           The document phase this gate guards (e.g. ``research``,
                         ``adr``); recorded in ``gate_phase`` and carried to the gate.
        submitter:       Deterministic, idempotent propose-and-submit callable;
                         returns the proposal id.
        gate_target:     The pure gate node to route into after the submit commits.
        revision_target: The phase's writer, routed to when the submitter refuses a
                         non-conformant body (the SAME target the gate uses on
                         ``request_changes``).

    Returns:
        An async node that proposes+submits and routes via ``Command.goto`` into
        the gate, committing ``authoring_proposal_ids`` / ``gate_phase`` /
        ``gate_pending_proposal_id`` - or, on a conformance refusal, routes to the
        writer with the specific check notes.
    """

    async def phase_submit_node(state: TeamState) -> Command:
        """Propose+submit (idempotent), commit the ids, route into the gate."""
        try:
            proposal_id = await submitter(state, phase)
        except ProposalRevisionRequiredError as exc:
            return Command(
                goto=revision_target,
                update={
                    "next": revision_target,
                    "gate_phase": phase,
                    "gate_verdict": VERDICT_REQUEST_CHANGES,
                    "validation_errors": list(exc.revision_notes),
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
            },
        )

    phase_submit_node.__name__ = f"phase_submit_{phase}"
    return phase_submit_node


def create_phase_gate_node(
    phase: str,
    *,
    approved_target: str,
    revision_target: str,
) -> WorkerNode:
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

    async def phase_gate_node(state: TeamState) -> Command:
        """Pause for the committed proposal's verdict, then route."""
        proposal_id = state.get("gate_pending_proposal_id")
        resume_value = interrupt(
            {
                "type": "document_approval_request",
                "phase": phase,
                "proposal_id": proposal_id,
                "feature": state.get("active_feature"),
            }
        )
        verdict, notes = _parse_verdict(resume_value)

        if verdict == VERDICT_APPROVED:
            return Command(
                goto=approved_target,
                update={
                    "next": approved_target,
                    "gate_phase": phase,
                    "gate_verdict": VERDICT_APPROVED,
                    "routing_error": None,
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
