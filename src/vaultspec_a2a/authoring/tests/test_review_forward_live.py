"""Live proof of the review-decision + apply-request delivery path (F30).

No mocks: this drives a real engine on loopback, resolved through the same
discovery-file contract every other live-engine suite in this package uses
(``service`` marked, skipped — never faked — when no engine is reachable). Set
``VAULTSPEC_ENGINE_SERVICE_JSON`` to the engine's discovery file before
selecting ``-m service``.

The audit finding this closes: a document proposal can reach ``needs_review``
in the engine, and a human can be told it was "approved" through this
repository's own respond route, while zero bytes ever reach disk — the a2a
respond route is a graph-resume signal only, and never advances the engine's
own decision. ``decide_review``/``request_apply`` (``authoring/session.py``)
are the typed client calls onto the two engine verbs that actually deliver a
changeset: ``POST /v1/reviews/{approval_id}/decisions`` then
``POST /v1/apply-requests``. This suite proves three things a drift guard
cannot: a real file lands on disk at the receipt's own reported path: a
retried apply under the SAME idempotency key produces exactly one write, not
two, because the ENGINE dedupes on the key (a same-process assertion alone
would only prove the key is stable); and an engine denial — self-approval, a
stale revision fence — surfaces distinguishably from success rather than as a
silent no-op.
"""

from __future__ import annotations

import pathlib
import uuid
from typing import TYPE_CHECKING, Any, cast

import pytest

from .. import (
    REVIEW_DECISION_APPROVE,
    AuthoringClient,
    AuthoringResponse,
    AuthoringSession,
    Denial,
    decide_review,
    derive_idempotency_key,
    mint_actor_token,
    request_apply,
)
from .._errors import AuthoringTransportError
from ..submitter import engine_scope_token

if TYPE_CHECKING:
    from ..discovery import EngineEndpoint

# The live engine authorises an authoring command against the run's own
# project, so materializing a real document binds to this checkout (mirrors
# test_submitter_live.py's own workspace binding) rather than a scratch
# directory the engine would not recognise as one.
_PROJECT = pathlib.Path(__file__).resolve().parents[4]


def _whole_document_op(feature: str) -> dict[str, Any]:
    """A minimally-conformant whole-document research proposal for *feature*.

    Carries real frontmatter (the engine fails a body closed at apply that
    ``vault set-body --check`` would reject at materialization — an AUTO gate
    once applied an empty scaffold; it no longer does), so this exercises the
    same shape the production submitter proposes, not a synthetic shortcut.
    """
    return {
        "child_key": f"research/{feature}-research.md",
        "operation": "create_document",
        "target": {
            "document": {
                "kind": "provisional_create",
                "provisional_doc_id": f"prov:{feature}",
                "doc_type": "research",
                "feature": feature,
                "title": "F30 delivery-path live proof",
                "collision_status": "available",
            }
        },
        "draft": {
            "mode": "whole_document",
            "body": (
                "---\n"
                "tags:\n"
                "  - '#research'\n"
                f"  - '#{feature}'\n"
                "date: '2026-08-05'\n"
                "modified: '2026-08-05'\n"
                "related: []\n"
                "---\n\n"
                f"# `{feature}` research: `f30 delivery-path live proof`\n\n"
                "## Summary\n\n"
                "Live proof body for the F30 review-decision + request-apply "
                "delivery path. Disposable test artifact, deleted by the test "
                "that materializes it.\n"
            ),
        },
    }


async def _mint(client: AuthoringClient, actor_id: str, kind: str) -> str:
    minted = await mint_actor_token(client, actor_id=actor_id, kind=kind)
    assert isinstance(minted, AuthoringResponse), f"mint denied: {minted}"
    token = minted.data.get("raw_token") if isinstance(minted.data, dict) else None
    assert isinstance(token, str) and token
    return token


def _find_review_item(data: object, changeset_id: str) -> dict[str, Any]:
    """Return the review-queue item's ``proposal`` object for *changeset_id*."""
    assert isinstance(data, dict), f"review-queue response is not an object: {data!r}"
    items = data.get("items")
    assert isinstance(items, list), f"review-queue response carries no items: {data!r}"
    for entry in items:
        proposal = entry.get("proposal") if isinstance(entry, dict) else None
        if isinstance(proposal, dict) and proposal.get("changeset_id") == changeset_id:
            return cast("dict[str, Any]", proposal)
    raise AssertionError(f"no review-queue item found for changeset {changeset_id!r}")


def _resolve_document_path(
    project_root: pathlib.Path, document_path: str
) -> pathlib.Path:
    """Resolve an apply receipt's ``document_path`` against the workspace root."""
    candidate = pathlib.Path(document_path)
    return candidate if candidate.is_absolute() else project_root / candidate


async def _propose_and_submit(
    client: AuthoringClient,
    session: AuthoringSession,
    *,
    run_id: str,
    feature: str,
    label: str,
) -> tuple[str, str]:
    """Create and submit one whole-document proposal.

    Returns ``(changeset_id, proposal_id)``.
    """
    changeset_id = session.new_changeset_id(label)
    created = await session.create_proposal(
        changeset_id=changeset_id,
        summary=f"f30 {label} live proof",
        operations=[_whole_document_op(feature)],
        idempotency_key=derive_idempotency_key(run_id, label, "create_proposal"),
    )
    assert isinstance(created, AuthoringResponse), f"create_proposal denied: {created}"
    revision = created.data["changeset_revision"]

    submitted = await session.submit(
        changeset_id=changeset_id,
        expected_revision=revision,
        summary=f"submit f30 {label} proof",
        idempotency_key=derive_idempotency_key(run_id, label, "submit"),
    )
    assert isinstance(submitted, AuthoringResponse), f"submit denied: {submitted}"
    proposal_id = submitted.data["proposal_id"]
    assert isinstance(proposal_id, str) and proposal_id
    return changeset_id, proposal_id


@pytest.mark.service
@pytest.mark.asyncio
async def test_decide_and_apply_materializes_a_file_with_single_application(
    live_engine: EngineEndpoint,
) -> None:
    """approve -> request_apply lands a real file, and a retried apply is a no-op.

    This is the F30 proof: the missing half of the delivery path is these two
    engine calls, and this asserts a file exists on disk at the exact path the
    apply receipt reports — not a 2xx, not an approval recorded, a file. The
    retried apply reuses the SAME idempotency key an operator retry would
    reproduce (run id + approval id + command, never fresh per call); dedupe on
    that key is enforced by the ENGINE, so a matching mtime/content after the
    retry is a real proof, not a same-process artifact of a stable key alone.
    """
    run_id = f"f30-{uuid.uuid4().hex[:10]}"
    feature = f"f30-review-proof-{uuid.uuid4().hex[:8]}"
    scope = engine_scope_token(_PROJECT)

    endpoint = live_engine.base_url, live_engine.bearer_token
    async with AuthoringClient(*endpoint) as client:
        author_token = await _mint(client, f"agent:{run_id}", "agent")
        reviewer_token = await _mint(client, f"reviewer:{run_id}", "human")
        client._actor_token = author_token

        session = AuthoringSession(client, run_id, project_scope=scope)
        created_session = await session.create_session(
            title=f"f30 {run_id}",
            idempotency_key=derive_idempotency_key(run_id, "create_session"),
        )
        assert isinstance(created_session, AuthoringResponse)

        changeset_id, proposal_id = await _propose_and_submit(
            client, session, run_id=run_id, feature=feature, label="proof"
        )

        queue = await client.get("/v1/review-queue")
        item = _find_review_item(queue.data, changeset_id)
        approval = item["approval"]
        approval_id = approval["approval_id"]
        reviewed_revision = approval["reviewed_proposal_revision"]

        decided = await decide_review(
            client,
            approval_id=approval_id,
            proposal_id=proposal_id,
            decision=REVIEW_DECISION_APPROVE,
            reviewed_revision=reviewed_revision,
            idempotency_key=derive_idempotency_key(run_id, approval_id, "approve"),
            actor_token=reviewer_token,
        )
        assert isinstance(decided, AuthoringResponse), f"approve denied: {decided}"

        apply_key = derive_idempotency_key(run_id, approval_id, "request_apply")
        first = await request_apply(
            client,
            changeset_id=changeset_id,
            approval_id=approval_id,
            idempotency_key=apply_key,
            actor_token=reviewer_token,
        )
        assert isinstance(first, AuthoringResponse), f"apply denied: {first}"
        assert first.data.get("child_outcome") == "applied", first.data
        receipt = first.data["receipt"]
        document_path = receipt["child"]["document_path"]
        assert isinstance(document_path, str) and document_path

        resolved_path = _resolve_document_path(_PROJECT, document_path)
        try:
            assert resolved_path.is_file(), (
                f"apply reported document_path={document_path!r} but no file "
                f"exists at {resolved_path}"
            )
            body_on_disk = resolved_path.read_text(encoding="utf-8")
            assert feature in body_on_disk
            mtime_after_first = resolved_path.stat().st_mtime_ns

            # Retry the identical forward under the SAME key. If a fresh key were
            # generated per call this would apply the document a second time —
            # the worst outcome available at this seam.
            second = await request_apply(
                client,
                changeset_id=changeset_id,
                approval_id=approval_id,
                idempotency_key=apply_key,
                actor_token=reviewer_token,
            )
            assert isinstance(second, AuthoringResponse), f"replay denied: {second}"
            assert second.data.get("status") in {"recorded", "replayed"}, second.data
            assert second.data.get("child_outcome") == "applied", second.data
            second_receipt = second.data["receipt"]
            assert second_receipt["child"]["document_path"] == document_path

            # Single application, proven on the FILESYSTEM: unchanged mtime and
            # byte-identical content after the retry, not merely a matching
            # receipt.
            assert resolved_path.stat().st_mtime_ns == mtime_after_first
            assert resolved_path.read_text(encoding="utf-8") == body_on_disk
        finally:
            resolved_path.unlink(missing_ok=True)


@pytest.mark.service
@pytest.mark.asyncio
async def test_self_approval_is_a_denial_not_a_silent_success(
    live_engine: EngineEndpoint,
) -> None:
    """The proposal's own author may not decide its own approval.

    A Denial, never a silently-accepted 2xx approval.
    """
    run_id = f"f30-self-{uuid.uuid4().hex[:10]}"
    feature = f"f30-self-approval-{uuid.uuid4().hex[:8]}"
    scope = engine_scope_token(_PROJECT)

    endpoint = live_engine.base_url, live_engine.bearer_token
    async with AuthoringClient(*endpoint) as client:
        author_token = await _mint(client, f"agent:{run_id}", "agent")
        client._actor_token = author_token

        session = AuthoringSession(client, run_id, project_scope=scope)
        created_session = await session.create_session(
            title=f"f30-self {run_id}",
            idempotency_key=derive_idempotency_key(run_id, "create_session"),
        )
        assert isinstance(created_session, AuthoringResponse)

        changeset_id, proposal_id = await _propose_and_submit(
            client, session, run_id=run_id, feature=feature, label="selfapprove"
        )

        queue = await client.get("/v1/review-queue")
        item = _find_review_item(queue.data, changeset_id)
        approval = item["approval"]
        approval_id = approval["approval_id"]
        reviewed_revision = approval["reviewed_proposal_revision"]

        # SAME author token deciding its own proposal must be a real, typed
        # Denial — never a silently-accepted approval.
        result = await decide_review(
            client,
            approval_id=approval_id,
            proposal_id=proposal_id,
            decision=REVIEW_DECISION_APPROVE,
            reviewed_revision=reviewed_revision,
            idempotency_key=derive_idempotency_key(run_id, approval_id, "approve"),
            actor_token=author_token,
        )
        assert isinstance(result, Denial), (
            f"self-approval must be a Denial, got {result!r}"
        )
        assert result.denial_kind, "a Denial without a denial_kind cannot be told apart"


@pytest.mark.service
@pytest.mark.asyncio
async def test_stale_reviewed_revision_is_a_typed_409_not_silently_decided(
    live_engine: EngineEndpoint,
) -> None:
    """A wrong revision attestation is refused loudly, never decided anyway.

    The edge contract's revision fence: the reviewer attests the exact
    ``changeset_revision`` the approval was opened against, and the engine
    refuses any mismatch with a typed 409 (``authoring_stale_review``) rather
    than deciding a superseded revision. This is the second distinguishable
    failure mode a forwarding caller must be able to tell apart from success —
    a transport-level typed error, not a Denial value.
    """
    run_id = f"f30-stale-{uuid.uuid4().hex[:10]}"
    feature = f"f30-stale-revision-{uuid.uuid4().hex[:8]}"
    scope = engine_scope_token(_PROJECT)

    endpoint = live_engine.base_url, live_engine.bearer_token
    async with AuthoringClient(*endpoint) as client:
        author_token = await _mint(client, f"agent:{run_id}", "agent")
        reviewer_token = await _mint(client, f"reviewer:{run_id}", "human")
        client._actor_token = author_token

        session = AuthoringSession(client, run_id, project_scope=scope)
        created_session = await session.create_session(
            title=f"f30-stale {run_id}",
            idempotency_key=derive_idempotency_key(run_id, "create_session"),
        )
        assert isinstance(created_session, AuthoringResponse)

        changeset_id, proposal_id = await _propose_and_submit(
            client, session, run_id=run_id, feature=feature, label="stalerev"
        )

        queue = await client.get("/v1/review-queue")
        item = _find_review_item(queue.data, changeset_id)
        approval_id = item["approval"]["approval_id"]

        with pytest.raises(AuthoringTransportError) as excinfo:
            await decide_review(
                client,
                approval_id=approval_id,
                proposal_id=proposal_id,
                decision=REVIEW_DECISION_APPROVE,
                reviewed_revision="changeset:f30stalefence0000000000000000000000000",
                idempotency_key=derive_idempotency_key(
                    run_id, approval_id, "fence-probe"
                ),
                actor_token=reviewer_token,
            )
        assert excinfo.value.status_code == 409
        assert excinfo.value.error_kind == "authoring_stale_review"
