"""Authoring session lifecycle and proposal verbs.

A thin, typed layer over :class:`AuthoringClient` that owns one authoring
session per run. The session generates its own engine-valid ids (session and
changeset), derives idempotency keys from stable run-local material, drives the
proposal verbs, and accumulates the Vaultspec ids it produces so the caller can
cross-reference them into thread state as references (never content).

Command discriminators match the engine ``CommandKind`` enum (snake_case,
`authoring/model.rs`): create_session, start_prompt_turn, create_proposal,
append_draft, replace_draft, submit_for_review, rebase. Reads
(snapshot/conflicts/provenance) are GETs with no command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ._envelope import AuthoringResponse
from ._ids import derive_idempotency_key, validate_id

if TYPE_CHECKING:
    from ._envelope import Denial
    from .client import AuthoringClient

__all__ = [
    "AuthoringSession",
    "close_authoring_session",
    "decide_review",
    "mint_actor_token",
    "request_apply",
]

_ACTOR_TOKENS_PATH = "/v1/actor-tokens"

# Review-decision wire values (engine `ApprovalDecision`, snake_case) and the
# `CommandKind` each maps to for the `ResolvedCommand` authorization extractor
# (`POST /v1/reviews/{approval_id}/decisions` deserializes a
# `CommandEnvelope<ReviewDecisionRequest>` and runs `run_authorization` on the
# envelope's own `command`, engine `http/mod.rs`). There is NO
# `submit_review_decision` `CommandKind` on the wire — that is the handler
# function name, not a command a caller may post. `edit` (RequestChanges) is the
# reject-with-notes device: it returns the changeset to Draft and stales the
# approval rather than terminating it.
REVIEW_DECISION_APPROVE = "approve"
REVIEW_DECISION_REJECT = "reject"
REVIEW_DECISION_EDIT = "edit"

_REVIEW_DECISION_COMMAND: dict[str, str] = {
    REVIEW_DECISION_APPROVE: "approve",
    REVIEW_DECISION_REJECT: "reject",
    REVIEW_DECISION_EDIT: "edit_proposal",
}


async def close_authoring_session(
    client: AuthoringClient,
    session_id: str,
    *,
    idempotency_key: str,
    reason: str | None = None,
) -> AuthoringResponse | Denial:
    """Close an engine authoring session benignly (``close_session``).

    ``POST /authoring/v1/sessions/{session_id}/close`` transitions the session
    ``Active -> Closed`` (stamps ``closed_at_ms``, emits ``session.closed`` on the
    durable feed) without tearing down its authoring work - the benign terminal a
    run's owner calls once its work has SUCCEEDED, distinct from ``cancel_session``.
    Idempotent by the route's contract (re-close or an already-cancelled session is
    a 200 no-op). The route REFUSES (422) while a run is genuinely active on the
    session; a2a-driven work creates no runs, so that guard never fires here.

    Takes the engine ``session_id`` string directly (the caller holds it from run
    state, not a bound :class:`AuthoringSession`). Dual-auth: the client's machine
    bearer plus its per-actor token.
    """
    path = f"/v1/sessions/{quote(session_id, safe='')}/close"
    payload: dict[str, Any] = {} if reason is None else {"reason": reason}
    return await client.post_command(
        path, command="close_session", payload=payload, idempotency_key=idempotency_key
    )


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
    caller stores it in worker-scoped runtime state and never logs it.
    """
    validate_id(actor_id, field="actor.id")
    payload: dict[str, Any] = {"actor": {"id": actor_id, "kind": kind}}
    if lifetime_ms is not None:
        payload["lifetime_ms"] = lifetime_ms
    return await client.post_bare(_ACTOR_TOKENS_PATH, payload)


async def decide_review(
    client: AuthoringClient,
    *,
    approval_id: str,
    proposal_id: str,
    decision: str,
    reviewed_revision: str,
    idempotency_key: str,
    comment: str | None = None,
    actor_token: str | None = None,
) -> AuthoringResponse | Denial:
    """Record a reviewer's decision on a queued approval (``submit_review_decision``).

    ``POST /authoring/v1/reviews/{approval_id}/decisions`` is the human-review
    half of the delivery path this repository's own respond route explicitly
    refuses to decide on a document proposal's behalf (the amended
    a2a-orchestration-edge contract: no second approval authority in A2A) — the
    engine review surface is the sole approval authority, and this is the typed
    client call onto it.

    ``decision`` is the engine ``ApprovalDecision`` wire value (``approve`` /
    ``reject`` / ``edit``); it is mapped onto the ``CommandKind`` the envelope
    must carry for the reviewer's own authorization check to run against the
    right command (see :data:`REVIEW_DECISION_APPROVE` and siblings). Passing
    an unrecognised value is refused client-side with ``ValueError`` before any
    round trip.

    ``reviewed_revision`` is the edge contract's REVISION FENCE: the caller
    attests the exact ``changeset_revision`` the approval was opened against
    (read from the same review-queue item ``approval_id``/``proposal_id`` came
    from). A stale attestation is refused by the engine as a typed 409
    (``authoring_stale_review``) rather than silently deciding a superseded
    revision — this function does not swallow that; it propagates as
    :class:`~vaultspec_a2a.authoring._errors.AuthoringTransportError`.

    The caller supplies ``idempotency_key`` explicitly (never derived here): per
    the submitter's own idempotency doctrine, a retry of the SAME decision must
    reproduce the SAME key so the engine dedupes rather than double-deciding —
    derive it from durable material (e.g. run id + approval id + command), never
    fresh per call.
    """
    command = _REVIEW_DECISION_COMMAND.get(decision)
    if command is None:
        raise ValueError(
            f"unknown review decision {decision!r}; expected one of "
            f"{sorted(_REVIEW_DECISION_COMMAND)}"
        )
    validate_id(approval_id, field="approval_id")
    validate_id(proposal_id, field="proposal_id")
    validate_id(reviewed_revision, field="reviewed_revision")
    payload: dict[str, Any] = {
        "proposal_id": proposal_id,
        "approval_id": approval_id,
        "decision": decision,
        "reviewed_revision": reviewed_revision,
    }
    if comment is not None:
        payload["comment"] = comment
    return await client.post_command(
        f"/v1/reviews/{quote(approval_id, safe='')}/decisions",
        command=command,
        payload=payload,
        idempotency_key=idempotency_key,
        actor_token=actor_token,
    )


async def request_apply(
    client: AuthoringClient,
    *,
    changeset_id: str,
    approval_id: str,
    idempotency_key: str,
    actor_token: str | None = None,
) -> AuthoringResponse | Denial:
    """Request the engine materialize an approved changeset (``request_apply``).

    ``POST /authoring/v1/apply-requests`` is the delivery half of the
    approve -> apply pair: a decision alone never writes a file, and calling
    this before ``approval_id`` carries an ``approve`` decision is refused by
    the engine as a :class:`Denial` (an in-domain business refusal), never
    silently ignored. A successful apply's receipt carries
    ``data.child_outcome == "applied"`` and the materialized
    ``data.receipt.child.{document_path,result_stem}`` — this function returns
    the engine's raw response; the caller reads those fields to learn what
    landed on disk.

    ``idempotency_key`` is supplied by the caller for the same reason
    :func:`decide_review` requires it explicitly: a retry that generates a
    FRESH key applies the same changeset a second time, which is the single
    worst outcome available at this seam. Derive it from durable material (run
    id + approval id + command) and reuse it byte-for-byte across a replay.
    """
    validate_id(changeset_id, field="changeset_id")
    validate_id(approval_id, field="approval_id")
    return await client.post_command(
        "/v1/apply-requests",
        command="request_apply",
        payload={"changeset_id": changeset_id, "approval_id": approval_id},
        idempotency_key=idempotency_key,
        actor_token=actor_token,
    )


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
    project_scope:
        The project this session's work belongs to, in the engine's scope
        spelling. It becomes the session's ``scope`` at creation, which is the
        one field the engine stores verbatim on the session record and therefore
        the only place a run's project can ride the closed authoring wire. Every
        mutating proposal verb below refuses while it is unset, so a proposal can
        never be issued from a session that named no project - the closed wire
        gives a proposal payload no field of its own, so its binding is the
        session it carries, and an unpinned session is a proposal fenced against
        whatever the engine's active workspace happens to be at command time.

        Optional here only so a caller may supply it to :meth:`create_session`
        instead; one of the two must provide it before any proposal.
    """

    def __init__(
        self,
        client: AuthoringClient,
        run_id: str,
        *,
        project_scope: str | None = None,
    ) -> None:
        self._client = client
        self._run_id = validate_id(run_id, field="run_id")
        self._seq = 0
        self._session_id: str | None = None
        self._engine_run_id: str | None = None
        self._project_scope = project_scope or None
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

    @property
    def project_scope(self) -> str | None:
        """The project every command on this session is fenced to."""
        return self._project_scope

    @property
    def engine_run_id(self) -> str | None:
        """The engine run id once ``start_turn`` has minted it (for execute)."""
        return self._engine_run_id

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
        """Derive the next idempotency key from run-local material.

        Keyed on ``run_id + command + sequence``. This matches the LangGraph
        replay model: a node re-run replays the same call order under the same
        ``run_id``, reproducing the byte-identical key the engine dedupes on. A
        within-session retry advances the sequence and is therefore a distinct
        command, not a dedupe of the prior one.
        """
        key = derive_idempotency_key(self._run_id, command, str(self._seq))
        self._seq += 1
        return key

    def _resolve_key(self, command: str, explicit: str | None) -> str:
        """Use an explicit run-local idempotency key when given, else the sequence.

        An explicit key lets a caller anchor idempotency in DURABLE material
        (e.g. run id + phase + revision) so a restarted worker that rebuilds the
        session reproduces byte-identical keys — the engine dedupes and no second
        session, changeset, or proposal is created. When omitted, the session
        falls back to its per-command sequence (the in-dispatch replay model).
        The advancing sequence is preserved either way so mixed explicit/implicit
        use never collides.
        """
        self._seq += 1
        if explicit is not None:
            return validate_id(explicit, field="idempotency_key")
        return derive_idempotency_key(self._run_id, command, str(self._seq - 1))

    def _record_changeset(self, changeset_id: str) -> None:
        if changeset_id not in self._changeset_ids:
            self._changeset_ids.append(changeset_id)

    def _bind_project(self, scope: str | None) -> str:
        """Settle the session's project from the binding and the call, or refuse.

        A session bound at construction ignores no caller: an explicit *scope*
        that agrees is redundant and accepted, one that disagrees is a command
        trying to fence this run's work to a different project and is refused
        rather than silently resolved either way.
        """
        if self._project_scope is not None:
            if scope is not None and scope != self._project_scope:
                raise ValueError(
                    f"session for run {self._run_id!r} is bound to project "
                    f"{self._project_scope!r}; refusing to open it under {scope!r}"
                )
            return self._project_scope
        if not scope:
            raise ValueError(
                f"session for run {self._run_id!r} names no project: supply "
                f"project_scope at construction or scope at create_session"
            )
        self._project_scope = scope
        return scope

    def _require_project(self, command: str) -> str:
        """Return the session's project, refusing an unpinned mutating command.

        A proposal command carries no project of its own - the engine's payloads
        are closed - so the session's binding is the whole of it. Refusing here
        keeps an unpinned session from producing work the engine would authorise
        against whatever workspace is active when the command lands.
        """
        if self._project_scope is None:
            raise RuntimeError(
                f"{command} requires a project-bound session; run "
                f"{self._run_id!r} opened none"
            )
        return self._project_scope

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def create_session(
        self,
        *,
        title: str,
        scope: str | None = None,
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        """Open the authoring session for this run (``create_session``).

        The engine generates the ``session_id`` and returns it in the receipt
        (``data.session_id``); the payload carries only ``scope`` and ``title``.
        A stable ``idempotency_key`` makes this a create-or-resume: a repeat call
        for the same run returns the same session (the engine dedupes) - which
        also means the project the session was FIRST opened under is the one it
        keeps, so a mid-run switch cannot re-scope work already in flight.

        ``scope`` is the session's project. A session constructed with a
        ``project_scope`` already carries it and needs none here; a caller may
        supply it instead, but not one that contradicts the binding.
        """
        effective_scope = self._bind_project(scope)
        result = await self._client.post_command(
            "/v1/sessions",
            command="create_session",
            payload={"scope": effective_scope, "title": title},
            idempotency_key=self._resolve_key("create_session", idempotency_key),
        )
        if isinstance(result, AuthoringResponse) and isinstance(result.data, dict):
            session_id = result.data.get("session_id")
            if isinstance(session_id, str):
                self._session_id = session_id
        return result

    async def start_turn(
        self,
        *,
        prompt: str,
        summary: str | None = None,
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        """Start a prompt turn within the session (``start_prompt_turn``)."""
        if self._session_id is None:
            raise RuntimeError("create_session must run before start_turn")
        payload: dict[str, Any] = {"prompt": prompt}
        if summary is not None:
            payload["summary"] = summary
        result = await self._client.post_command(
            f"/v1/sessions/{self._session_id}/turns",
            command="start_prompt_turn",
            payload=payload,
            idempotency_key=self._resolve_key("start_prompt_turn", idempotency_key),
        )
        if isinstance(result, AuthoringResponse) and isinstance(result.data, dict):
            run_id = result.data.get("run_id")
            if isinstance(run_id, str):
                self._engine_run_id = run_id
        return result

    # ------------------------------------------------------------------
    # Proposal verbs (mutating)
    # ------------------------------------------------------------------

    async def create_proposal(
        self,
        *,
        changeset_id: str,
        summary: str,
        operations: list[dict[str, Any]],
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        """Create a proposal changeset (``create_proposal``)."""
        if self._session_id is None:
            raise RuntimeError("create_session must run before create_proposal")
        self._require_project("create_proposal")
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
            idempotency_key=self._resolve_key("create_proposal", idempotency_key),
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
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        """Append operations to an existing draft (``append_draft``)."""
        return await self._draft_mutation(
            "append",
            changeset_id,
            expected_revision,
            summary,
            operations,
            idempotency_key,
        )

    async def replace_draft(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
        operations: list[dict[str, Any]],
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        """Replace a draft's operations (``replace_draft``)."""
        return await self._draft_mutation(
            "replace",
            changeset_id,
            expected_revision,
            summary,
            operations,
            idempotency_key,
        )

    async def _draft_mutation(
        self,
        verb: str,
        changeset_id: str,
        expected_revision: str,
        summary: str,
        operations: list[dict[str, Any]],
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        command = "append_draft" if verb == "append" else "replace_draft"
        self._require_project(command)
        validate_id(changeset_id, field="changeset_id")
        validate_id(expected_revision, field="expected_revision")
        return await self._client.post_command(
            f"/v1/proposals/{changeset_id}/{verb}",
            command=command,
            payload={
                "changeset_id": changeset_id,
                "expected_revision": expected_revision,
                "summary": summary,
                "operations": operations,
            },
            idempotency_key=self._resolve_key(command, idempotency_key),
        )

    async def submit(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        """Submit a proposal into human review (``submit_for_review``).

        Submission is where the engine mints the review-facing ``proposal_id``
        (the changeset id addresses drafts; the proposal id addresses the
        opened approval). It is captured from the receipt into the run's
        produced-id references so thread state can match the engine's records.
        """
        self._require_project("submit_for_review")
        validate_id(changeset_id, field="changeset_id")
        validate_id(expected_revision, field="expected_revision")
        result = await self._client.post_command(
            f"/v1/proposals/{changeset_id}/submit",
            command="submit_for_review",
            payload={"expected_revision": expected_revision, "summary": summary},
            idempotency_key=self._resolve_key("submit_for_review", idempotency_key),
        )
        if isinstance(result, AuthoringResponse) and isinstance(result.data, dict):
            proposal_id = result.data.get("proposal_id")
            if isinstance(proposal_id, str) and proposal_id not in self._proposal_ids:
                self._proposal_ids.append(proposal_id)
        return result

    async def rebase(
        self,
        *,
        changeset_id: str,
        expected_revision: str,
        summary: str,
        idempotency_key: str | None = None,
    ) -> AuthoringResponse | Denial:
        """Rebase a proposal onto the latest base revision (``rebase``)."""
        self._require_project("rebase")
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
            idempotency_key=self._resolve_key("rebase", idempotency_key),
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
