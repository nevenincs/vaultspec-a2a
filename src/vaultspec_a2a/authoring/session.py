"""Authoring session lifecycle and proposal verbs (ADR R3).

A thin, typed layer over :class:`AuthoringClient` that owns one authoring
session per run. The session generates its own engine-valid ids (session and
changeset), derives idempotency keys from stable run-local material, drives the
proposal verbs, and accumulates the Vaultspec ids it produces so the caller can
cross-reference them into thread state as references (never content).

Command discriminators match the engine ``CommandKind`` enum (snake_case,
`authoring/model.rs`): create_session, start_prompt_turn, create_proposal,
append_draft, replace_draft, validate_proposal, submit_for_review, rebase,
cancel_proposal. Reads (snapshot/conflicts/provenance) are GETs with no command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._envelope import AuthoringResponse
from ._ids import derive_idempotency_key, validate_id

if TYPE_CHECKING:
    from ._envelope import Denial
    from .client import AuthoringClient

__all__ = ["AuthoringSession", "mint_actor_token"]

_ACTOR_TOKENS_PATH = "/v1/actor-tokens"


async def mint_actor_token(
    client: AuthoringClient,
    *,
    actor_id: str,
    kind: str = "agent",
    lifetime_ms: int | None = None,
) -> AuthoringResponse | Denial:
    """Mint a per-actor token via the bare bootstrap route (bearer-gated only).

    ``POST /authoring/v1/actor-tokens`` is the sole non-enveloped mutating
    route: it takes ``{actor: {id, kind}, lifetime_ms?}`` and needs no per-actor
    token yet. The raw token is returned once, in the response ``data`` — the
    caller stores it in worker-scoped runtime state and never logs it (R7).
    """
    validate_id(actor_id, field="actor.id")
    payload: dict[str, Any] = {"actor": {"id": actor_id, "kind": kind}}
    if lifetime_ms is not None:
        payload["lifetime_ms"] = lifetime_ms
    return await client.post_bare(_ACTOR_TOKENS_PATH, payload)


class AuthoringSession:
    """One authoring session bound to a single run.

    Parameters
    ----------
    client:
        The authoring client (already carrying the machine bearer and the
        per-actor token for this run's role).
    run_id:
        Stable run-local identifier used as idempotency-key material and as the
        seed for generated session/changeset ids. Must satisfy the id grammar.
    """

    def __init__(self, client: AuthoringClient, run_id: str) -> None:
        self._client = client
        self._run_id = validate_id(run_id, field="run_id")
        self._seq = 0
        self._session_id: str | None = None
        # Produced Vaultspec ids, accumulated for thread-state cross-reference.
        self._changeset_ids: list[str] = []
        self._proposal_ids: list[str] = []

    # ------------------------------------------------------------------
    # Identity and references
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        """The engine session id once ``create_session`` has run."""
        return self._session_id

    def new_changeset_id(self, label: str) -> str:
        """Mint a deterministic, engine-valid changeset id for this run."""
        candidate = f"cs:{self._run_id}:{validate_id(label, field='label')}"
        return validate_id(candidate, field="changeset_id")

    def state_references(self) -> dict[str, Any]:
        """Return the produced-id references to fold into thread state.

        References only (D5): session id and the changeset/proposal ids this
        session created — never document content.
        """
        return {
            "authoring_session_id": self._session_id,
            "authoring_changeset_ids": list(self._changeset_ids),
            "authoring_proposal_ids": list(self._proposal_ids),
        }

    def _next_key(self, command: str) -> str:
        key = derive_idempotency_key(self._run_id, command, str(self._seq))
        self._seq += 1
        return key

    def _record_changeset(self, changeset_id: str) -> None:
        if changeset_id not in self._changeset_ids:
            self._changeset_ids.append(changeset_id)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def create_session(
        self, *, scope: str, title: str
    ) -> AuthoringResponse | Denial:
        """Open the authoring session for this run (``create_session``).

        The engine generates the ``session_id`` and returns it in the receipt
        (``data.session_id``); the payload carries only ``scope`` and ``title``.
        """
        result = await self._client.post_command(
            "/v1/sessions",
            command="create_session",
            payload={"scope": scope, "title": title},
            idempotency_key=self._next_key("create_session"),
        )
        if isinstance(result, AuthoringResponse) and isinstance(result.data, dict):
            session_id = result.data.get("session_id")
            if isinstance(session_id, str):
                self._session_id = session_id
        return result

    async def start_turn(
        self, *, prompt: str, summary: str | None = None
    ) -> AuthoringResponse | Denial:
        """Start a prompt turn within the session (``start_prompt_turn``)."""
        if self._session_id is None:
            raise RuntimeError("create_session must run before start_turn")
        payload: dict[str, Any] = {"prompt": prompt}
        if summary is not None:
            payload["summary"] = summary
        return await self._client.post_command(
            f"/v1/sessions/{self._session_id}/turns",
            command="start_prompt_turn",
            payload=payload,
            idempotency_key=self._next_key("start_prompt_turn"),
        )

    # ------------------------------------------------------------------
    # Proposal verbs (mutating)
    # ------------------------------------------------------------------

    async def create_proposal(
        self,
        *,
        changeset_id: str,
        summary: str,
        operations: list[dict[str, Any]],
    ) -> AuthoringResponse | Denial:
        """Create a proposal changeset (``create_proposal``)."""
        if self._session_id is None:
            raise RuntimeError("create_session must run before create_proposal")
        validate_id(changeset_id, field="changeset_id")
        result = await self._client.post_command(
            "/v1/proposals",
            command="create_proposal",
            payload={
                "session_id": self._session_id,
                "changeset_id": changeset_id,
                "summary": summary,
                "operations": operations,
            },
            idempotency_key=self._next_key("create_proposal"),
        )
        self._record_changeset(changeset_id)
        return result

    async def append_draft(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
        operations: list[dict[str, Any]],
    ) -> AuthoringResponse | Denial:
        """Append operations to an existing draft (``append_draft``)."""
        return await self._draft_mutation(
            "append", changeset_id, expected_revision, summary, operations
        )

    async def replace_draft(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
        operations: list[dict[str, Any]],
    ) -> AuthoringResponse | Denial:
        """Replace a draft's operations (``replace_draft``)."""
        return await self._draft_mutation(
            "replace", changeset_id, expected_revision, summary, operations
        )

    async def _draft_mutation(
        self,
        verb: str,
        changeset_id: str,
        expected_revision: str,
        summary: str,
        operations: list[dict[str, Any]],
    ) -> AuthoringResponse | Denial:
        validate_id(changeset_id, field="changeset_id")
        validate_id(expected_revision, field="expected_revision")
        command = "append_draft" if verb == "append" else "replace_draft"
        return await self._client.post_command(
            f"/v1/proposals/{changeset_id}/{verb}",
            command=command,
            payload={
                "changeset_id": changeset_id,
                "expected_revision": expected_revision,
                "summary": summary,
                "operations": operations,
            },
            idempotency_key=self._next_key(command),
        )

    async def submit(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
    ) -> AuthoringResponse | Denial:
        """Submit a validated proposal into human review (``submit_for_review``)."""
        validate_id(changeset_id, field="changeset_id")
        validate_id(expected_revision, field="expected_revision")
        return await self._client.post_command(
            f"/v1/proposals/{changeset_id}/submit",
            command="submit_for_review",
            payload={"expected_revision": expected_revision, "summary": summary},
            idempotency_key=self._next_key("submit_for_review"),
        )

    async def rebase(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
    ) -> AuthoringResponse | Denial:
        """Rebase a proposal onto the latest base revision (``rebase``)."""
        validate_id(changeset_id, field="changeset_id")
        validate_id(expected_revision, field="expected_revision")
        return await self._client.post_command(
            f"/v1/proposals/{changeset_id}/rebase",
            command="rebase",
            payload={
                "changeset_id": changeset_id,
                "expected_revision": expected_revision,
                "summary": summary,
            },
            idempotency_key=self._next_key("rebase"),
        )

    async def cancel_proposal(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
    ) -> AuthoringResponse | Denial:
        """Cancel a proposal (``cancel_proposal``)."""
        validate_id(changeset_id, field="changeset_id")
        validate_id(expected_revision, field="expected_revision")
        return await self._client.post_command(
            f"/v1/proposals/{changeset_id}/cancel",
            command="cancel_proposal",
            payload={
                "changeset_id": changeset_id,
                "expected_revision": expected_revision,
                "summary": summary,
            },
            idempotency_key=self._next_key("cancel_proposal"),
        )

    # ------------------------------------------------------------------
    # Proposal reads (GET, no command)
    # ------------------------------------------------------------------

    async def snapshot(self, changeset_id: str) -> AuthoringResponse:
        """Read a proposal snapshot (history, latest, latest_validation)."""
        validate_id(changeset_id, field="changeset_id")
        return await self._client.get(
            f"/v1/proposals/{changeset_id}/snapshot", with_actor=True
        )

    async def conflicts(self, changeset_id: str) -> AuthoringResponse:
        """Read a proposal's conflicts."""
        validate_id(changeset_id, field="changeset_id")
        return await self._client.get(
            f"/v1/proposals/{changeset_id}/conflicts", with_actor=True
        )

    async def provenance(self, changeset_id: str) -> AuthoringResponse:
        """Read a proposal's provenance."""
        validate_id(changeset_id, field="changeset_id")
        return await self._client.get(
            f"/v1/proposals/{changeset_id}/provenance", with_actor=True
        )
