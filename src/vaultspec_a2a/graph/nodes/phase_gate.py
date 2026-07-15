"""Generalized per-phase human-approval gate (adr-authoring-orchestration S05).

The phase gate generalizes the plan-approval pattern (commit ``f5f650d``,
``create_plan_approval_node``) from a single execution gate into a factory
parameterized by document phase. A resumed LangGraph node re-runs from its start,
so everything before the ``interrupt()`` call must be deterministic and
replay-safe. The gate's pre-interrupt side effect is a propose-and-submit through
an injected :class:`DocumentProposalSubmitter`, which is replay-safe by
construction: the authoring client derives idempotency keys from stable run-local
material, so the replayed submit on resume is a no-op that returns the same
proposal id.

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
    "create_phase_gate_node",
]

VERDICT_APPROVED = "approved"
VERDICT_REJECTED = "rejected"
VERDICT_REQUEST_CHANGES = "request_changes"

_REVISION_VERDICTS = frozenset({VERDICT_REJECTED, VERDICT_REQUEST_CHANGES})


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


def create_phase_gate_node(
    phase: str,
    submitter: DocumentProposalSubmitter,
    *,
    approved_target: str,
    revision_target: str,
) -> WorkerNode:
    """Create a replay-safe per-phase document-approval gate node.

    Args:
        phase:           The document phase this gate guards (e.g. ``research``,
                         ``adr``); carried in the interrupt payload and recorded
                         in ``gate_phase``.
        submitter:       Deterministic, idempotent propose-and-submit callable
                         run before the interrupt; returns the proposal id.
        approved_target: Node to route to when the reviewer approves.
        revision_target: Node to route to on ``rejected`` / ``request_changes``
                         (the phase's writer); reviewer notes are appended to
                         ``validation_errors``.

    Returns:
        An async node that proposes+submits, interrupts for the human verdict on
        first pass, and on resume routes via ``Command.goto`` with the verdict
        recorded in ``gate_phase`` / ``gate_verdict``.
    """

    async def phase_gate_node(state: TeamState) -> Command:
        """Propose+submit (idempotent), pause for the verdict, then route."""
        # Deterministic pre-interrupt side effect: replay-safe because the
        # submitter is idempotent and returns the same proposal id on resume.
        proposal_id = await submitter(state, phase)
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
                    "authoring_proposal_ids": [proposal_id],
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
                "authoring_proposal_ids": [proposal_id],
                "validation_errors": [revise_note],
            },
        )

    phase_gate_node.__name__ = f"phase_gate_{phase}"
    return phase_gate_node
