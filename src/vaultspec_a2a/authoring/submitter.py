"""Production ``DocumentProposalSubmitter`` for document phase gates (ADR PW1).

The phase gate (``graph/nodes/phase_gate.py``) calls an injected
:class:`~vaultspec_a2a.graph.nodes.phase_gate.DocumentProposalSubmitter` before
its ``interrupt()`` on every pass — including the replay on resume and after a
worker restart. This concrete implementation makes that call a real, whole-
document propose-and-submit through the engine authoring API, and it is
replay-exact by construction so a repeated call for the same run/phase/revision
is a no-op that returns the same proposal id.

Idempotency is anchored in DURABLE run material, not an in-memory sequence. There
is ONE engine session per run (``run_id = thread_id``): a constant
``create_session`` key makes every call a create-or-resume of the same session,
reused across the research and adr phases. Each mutating call passes an explicit
key derived from ``thread_id + phase + command + revision cycle`` (PW1), so each
phase/revision is its own changeset and proposal, and every key is reproduced
byte-for-byte on replay and after a worker restart — the engine dedupes, never
creating a second session, changeset, or proposal.

Token hygiene (conformance R7): the submitter holds NO token. It reads the
machine bearer and the calling role's per-actor token from the worker-scoped
:class:`~vaultspec_a2a.worker.token_store.RunTokenStore` at call time, so a
restart re-resolves identity correctly and no token is ever captured, logged, or
checkpointed. Document content is submitted to the engine and never written to
``.vault/**`` and never persisted into LangGraph state (only the Rust-backend
proposal/changeset ids are, via the gate node).

Failures fail closed with a typed, actionable error (:class:`SubmitterError`
subclasses) surfaced as a truthful run failure — never a silent skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._envelope import AuthoringResponse, Denial
from ._errors import AuthoringError
from ._ids import derive_idempotency_key
from .client import AuthoringClient
from .session import AuthoringSession

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..thread.state import TeamState
    from ..worker.token_store import RunTokenStore

__all__ = [
    "CredentialsMissingError",
    "DocumentProposalSubmitter",
    "DocumentUnavailableError",
    "EngineUnavailableError",
    "PhaseAuthoringSpec",
    "ProposalDeniedError",
    "RoleConfigInvalidError",
    "SubmitterError",
]


class SubmitterError(AuthoringError):
    """Base of the fail-closed submitter error family (ADR PW4).

    Every member is actionable and surfaced as a truthful run failure state, so a
    run that cannot author never proceeds vaguely.
    """


class EngineUnavailableError(SubmitterError):
    """The engine origin is unconfigured or the run is missing its identity."""


class CredentialsMissingError(SubmitterError):
    """The machine bearer or the calling role's actor token is not held."""


class RoleConfigInvalidError(SubmitterError):
    """No authoring role/document configuration exists for the requested phase."""


class DocumentUnavailableError(SubmitterError):
    """The phase produced no document body to submit."""


class ProposalDeniedError(SubmitterError):
    """The engine returned an in-domain denial (value, not transport error)."""

    def __init__(self, stage: str, denial: Denial) -> None:
        self.stage = stage
        self.denial_kind = denial.denial_kind
        self.reason = denial.reason
        super().__init__(
            f"authoring {stage} denied ({denial.denial_kind}): "
            f"{denial.reason or 'no reason given'}"
        )


@dataclass(frozen=True, slots=True)
class PhaseAuthoringSpec:
    """Per-phase authoring configuration, supplied by the construction site (S13).

    Parameters
    ----------
    document_role:
        The role identifier whose per-actor token authors this phase's document;
        keyed into :class:`RunTokenStore` (the engine provisions one token per
        role at run-start).
    writer_message_name:
        The graph node name the phase's document author writes under; the worker
        node stamps ``AIMessage.name`` with it, so the latest such message is the
        document body to submit.
    doc_type:
        The engine document type for the proposal target (e.g. ``research``,
        ``adr``).
    """

    document_role: str
    writer_message_name: str
    doc_type: str


def _latest_document(state: TeamState, writer_message_name: str) -> tuple[str, int]:
    """Return ``(body, revision_cycle)`` for the phase's document from state.

    The body is the content of the most recent message the phase's author wrote
    (``AIMessage.name == writer_message_name``); the revision cycle is how many
    such messages exist — one per author pass, so a request-changes revision
    advances it, making the idempotency key advance with the revision.
    """
    bodies: list[str] = []
    for message in state.get("messages", []):
        if getattr(message, "name", None) != writer_message_name:
            continue
        content = getattr(message, "content", "")
        text = content if isinstance(content, str) else str(content)
        if text.strip():
            bodies.append(text)
    if not bodies:
        raise DocumentUnavailableError(
            f"phase author {writer_message_name!r} produced no document body to "
            f"submit; the run cannot propose an empty document"
        )
    return bodies[-1], len(bodies)


class DocumentProposalSubmitter:
    """Whole-document propose-and-submit for a document phase (ADR PW1).

    Constructed per run by the worker lifecycle (S13/PW2) from run-start facts:
    the engine origin, the run's :class:`RunTokenStore`, the feature tag, and the
    per-phase authoring specs. Conforms to the phase-gate
    ``DocumentProposalSubmitter`` Protocol.
    """

    def __init__(
        self,
        *,
        engine_base_url: str,
        token_store: RunTokenStore,
        feature: str,
        phases: Mapping[str, PhaseAuthoringSpec],
    ) -> None:
        if not engine_base_url:
            raise EngineUnavailableError(
                "production submitter constructed without an engine origin"
            )
        self._engine_base_url = engine_base_url.rstrip("/")
        self._token_store = token_store
        self._feature = feature
        self._phases = dict(phases)

    async def __call__(self, state: TeamState, phase: str) -> str:
        """Propose and submit the phase's document; return its proposal id."""
        thread_id = state.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise EngineUnavailableError(
                "run state carries no thread_id; cannot resolve run identity"
            )
        spec = self._phases.get(phase)
        if spec is None:
            raise RoleConfigInvalidError(
                f"no authoring configuration for document phase {phase!r}"
            )

        bearer = self._token_store.engine_bearer(thread_id)
        if not bearer:
            raise CredentialsMissingError(
                f"no engine bearer held for run {thread_id}; the run was not "
                f"provisioned with authoring credentials"
            )
        actor_token = self._token_store.actor_token(thread_id, spec.document_role)
        if not actor_token:
            raise CredentialsMissingError(
                f"no actor token held for role {spec.document_role!r} on run "
                f"{thread_id}; identity is unavailable for authoring"
            )

        body, revision_cycle = _latest_document(state, spec.writer_message_name)
        return await self._propose_and_submit(
            thread_id=thread_id,
            phase=phase,
            spec=spec,
            body=body,
            revision_cycle=revision_cycle,
            bearer=bearer,
            actor_token=actor_token,
        )

    async def _propose_and_submit(
        self,
        *,
        thread_id: str,
        phase: str,
        spec: PhaseAuthoringSpec,
        body: str,
        revision_cycle: int,
        bearer: str,
        actor_token: str,
    ) -> str:
        rev = str(revision_cycle)
        async with AuthoringClient(
            self._engine_base_url, bearer, actor_token=actor_token
        ) as client:
            # One session per run (run_id = thread_id): a constant create_session
            # key makes every call a create-or-resume of the same engine session,
            # reused across the research and adr phases. The per-command keys below
            # add phase + revision so each phase/revision is its own changeset and
            # proposal, and all keys are reproduced byte-for-byte on replay and
            # after a restart (PW1).
            session = AuthoringSession(client, thread_id)
            created_session = await session.create_session(
                scope="repo",
                title=f"{self._feature} authoring",
                idempotency_key=derive_idempotency_key(thread_id, "create_session"),
            )
            self._reject_denial("create_session", created_session)

            changeset_id = session.new_changeset_id(f"{phase}-r{revision_cycle}")
            created = await session.create_proposal(
                changeset_id=changeset_id,
                summary=f"{self._feature} {phase} document (r{rev})",
                operations=[self._whole_document_op(thread_id, phase, rev, spec, body)],
                idempotency_key=derive_idempotency_key(
                    thread_id, phase, "create_proposal", rev
                ),
            )
            self._reject_denial("create_proposal", created)
            revision = self._changeset_revision(created)

            submitted = await session.submit(
                changeset_id=changeset_id,
                expected_revision=revision,
                summary=f"submit {self._feature} {phase} (r{rev})",
                idempotency_key=derive_idempotency_key(
                    thread_id, phase, "submit", rev
                ),
            )
            self._reject_denial("submit", submitted)
            return self._proposal_id(submitted)

    def _whole_document_op(
        self,
        thread_id: str,
        phase: str,
        rev: str,
        spec: PhaseAuthoringSpec,
        body: str,
    ) -> dict[str, Any]:
        """Build the engine-proven whole-document create operation.

        Shape matches the live-verified ``create_document`` op (a
        ``provisional_create`` document target plus a ``whole_document`` draft).
        Every id is deterministic in the run material so a replayed create is a
        byte-identical, deduped no-op.
        """
        return {
            "child_key": f"{spec.doc_type}/{self._feature}-{phase}.md",
            "operation": "create_document",
            "target": {
                "document": {
                    "kind": "provisional_create",
                    "provisional_doc_id": f"prov:{thread_id}:{phase}:r{rev}",
                    "doc_type": spec.doc_type,
                    "feature": self._feature,
                    "title": f"{self._feature} {phase}",
                    "collision_status": "available",
                }
            },
            "draft": {"mode": "whole_document", "body": body},
        }

    @staticmethod
    def _reject_denial(stage: str, result: AuthoringResponse | Denial) -> None:
        if isinstance(result, Denial):
            raise ProposalDeniedError(stage, result)

    @staticmethod
    def _changeset_revision(result: AuthoringResponse | Denial) -> str:
        if isinstance(result, AuthoringResponse) and isinstance(result.data, dict):
            revision = result.data.get("changeset_revision")
            if isinstance(revision, str) and revision:
                return revision
        raise SubmitterError(
            "create_proposal receipt carried no changeset_revision; cannot submit"
        )

    @staticmethod
    def _proposal_id(result: AuthoringResponse | Denial) -> str:
        if isinstance(result, AuthoringResponse) and isinstance(result.data, dict):
            proposal_id = result.data.get("proposal_id")
            if isinstance(proposal_id, str) and proposal_id:
                return proposal_id
        raise SubmitterError("submit receipt carried no proposal_id")
