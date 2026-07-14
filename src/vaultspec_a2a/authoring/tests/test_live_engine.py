"""Live integration tests against the running dashboard engine (ADR R3, S17).

No mocks: these exercise the real ``AuthoringClient`` against a live engine on
loopback, resolved through the discovery-file contract. They are ``service``
marked and excluded from the default profile; when selected with no reachable
engine they skip with a runbook pointer (an infrastructure gate, not a masked
code failure). Set ``VAULTSPEC_ENGINE_SERVICE_JSON`` to point at the engine's
discovery file (a ``--no-seat`` serve writes a workspace-local one).

Verified live at authoring time: catalog schema ``authoring.semantic_tools.v1``
with 7 tools; ``mint`` returns ``data.raw_token``; ``create_session`` generates
the ``session_id`` server-side; a whole-document ``create_document`` proposal
(``provisional_create`` document ref + ``whole_document`` draft) returns
``status: draft`` with a ``changeset_revision``; idempotent replay on a repeated
key returns the same receipt.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from .. import AuthoringClient, AuthoringSession, mint_actor_token
from .._envelope import AuthoringResponse
from .._errors import AuthoringTransportError

_STALE_MS = 120_000
_EXPECTED_TOOL_NAMES = {
    "read_context",
    "search_graph",
    "propose_changeset",
    "validate_proposal",
    "request_approval",
    "cancel",
    "request_apply",
}


def _service_json_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("VAULTSPEC_ENGINE_SERVICE_JSON")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".vaultspec" / "service.json")
    return candidates


def _resolve_engine() -> tuple[str, str] | None:
    """Resolve a live engine (base_url, bearer) via the discovery contract."""
    now_ms = int(time.time() * 1000)
    for path in _service_json_candidates():
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        heartbeat = info.get("last_heartbeat")
        if isinstance(heartbeat, (int, float)) and now_ms - heartbeat > _STALE_MS:
            continue
        port = info.get("port")
        token = info.get("service_token")
        if not isinstance(port, int) or not isinstance(token, str):
            continue
        base_url = f"http://127.0.0.1:{port}"
        try:
            resp = httpx.get(f"{base_url}/health", timeout=3.0)
        except httpx.HTTPError:
            continue
        if resp.status_code == 200:
            return base_url, token
    return None


@pytest.fixture(scope="module")
def engine() -> tuple[str, str]:
    resolved = _resolve_engine()
    if resolved is None:
        pytest.skip(
            "no reachable authoring engine; start `vaultspec serve` per the "
            "runbook or set VAULTSPEC_ENGINE_SERVICE_JSON"
        )
    return resolved


@pytest_asyncio.fixture
async def client(engine: tuple[str, str]):
    base_url, bearer = engine
    async with AuthoringClient(base_url, bearer) as authoring_client:
        yield authoring_client


async def _authenticated_session(
    client: AuthoringClient, run_id: str
) -> AuthoringSession:
    """Mint an actor token, bind it, open a session, and return it."""
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    assert isinstance(minted.data, dict)
    raw_token = minted.data.get("raw_token")
    assert isinstance(raw_token, str) and raw_token
    client._actor_token = raw_token
    session = AuthoringSession(client, run_id)
    created = await session.create_session(scope="repo", title=f"s17 {run_id}")
    assert isinstance(created, AuthoringResponse)
    assert session.session_id is not None
    return session


def _whole_document_op(run_id: str) -> dict[str, Any]:
    return {
        "child_key": f"research/s17-{run_id}.md",
        "operation": "create_document",
        "target": {
            "document": {
                "kind": "provisional_create",
                "provisional_doc_id": f"prov:{run_id}",
                "doc_type": "research",
                "feature": "a2a-edge-conformance",
                "title": "S17 probe",
                "collision_status": "available",
            }
        },
        "draft": {"mode": "whole_document", "body": "# S17\n\nLive proof body."},
    }


@pytest.mark.service
@pytest.mark.asyncio
async def test_catalog_schema_and_tools(client: AuthoringClient) -> None:
    catalog = await client.get("/v1/agent-tools")
    assert isinstance(catalog.data, dict)
    assert catalog.data.get("schema_version") == "authoring.semantic_tools.v1"
    names = {tool["name"] for tool in catalog.data["tools"]}
    assert names == _EXPECTED_TOOL_NAMES


@pytest.mark.service
@pytest.mark.asyncio
async def test_mint_actor_token_returns_raw_token(client: AuthoringClient) -> None:
    run_id = f"s17-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    assert isinstance(minted.data, dict)
    assert isinstance(minted.data.get("raw_token"), str)


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_session_generates_server_id(client: AuthoringClient) -> None:
    run_id = f"s17-{uuid.uuid4().hex[:8]}"
    session = await _authenticated_session(client, run_id)
    assert session.session_id is not None
    assert session.session_id.startswith("session:")


@pytest.mark.service
@pytest.mark.asyncio
async def test_whole_document_proposal_creates_draft(
    client: AuthoringClient,
) -> None:
    run_id = f"s17-{uuid.uuid4().hex[:8]}"
    session = await _authenticated_session(client, run_id)
    changeset_id = session.new_changeset_id("wholedoc")
    result = await session.create_proposal(
        changeset_id=changeset_id,
        summary="s17 whole-document proposal",
        operations=[_whole_document_op(run_id)],
    )
    assert isinstance(result, AuthoringResponse)
    assert isinstance(result.data, dict)
    assert result.data.get("status") == "draft"
    assert isinstance(result.data.get("changeset_revision"), str)
    # The produced changeset id is cross-referenced for thread state.
    assert changeset_id in session.state_references()["authoring_changeset_ids"]


@pytest.mark.service
@pytest.mark.asyncio
async def test_submit_captures_proposal_id_reference(
    client: AuthoringClient,
) -> None:
    run_id = f"s17-{uuid.uuid4().hex[:8]}"
    session = await _authenticated_session(client, run_id)
    changeset_id = session.new_changeset_id("submitme")
    created = await session.create_proposal(
        changeset_id=changeset_id,
        summary="s17 submit path",
        operations=[_whole_document_op(run_id)],
    )
    assert isinstance(created, AuthoringResponse)
    revision = created.data["changeset_revision"]

    submitted = await session.submit(
        changeset_id=changeset_id, expected_revision=revision, summary="s17 submit"
    )
    assert isinstance(submitted, AuthoringResponse)
    assert isinstance(submitted.data, dict)
    proposal_id = submitted.data.get("proposal_id")
    assert isinstance(proposal_id, str) and proposal_id
    # The proposal id is minted at submit and cross-referenced into thread state.
    assert proposal_id in session.state_references()["authoring_proposal_ids"]


@pytest.mark.service
@pytest.mark.asyncio
async def test_idempotent_replay_returns_same_receipt(
    client: AuthoringClient,
) -> None:
    run_id = f"s17-{uuid.uuid4().hex[:8]}"
    session = await _authenticated_session(client, run_id)
    changeset_id = f"cs:{run_id}:idem"
    payload = {
        "session_id": session.session_id,
        "changeset_id": changeset_id,
        "summary": "idempotent replay",
        "operations": [_whole_document_op(run_id)],
    }
    key = f"idk-idem-{run_id}"
    first = await client.post_command(
        "/v1/proposals", "create_proposal", payload, idempotency_key=key
    )
    second = await client.post_command(
        "/v1/proposals", "create_proposal", payload, idempotency_key=key
    )
    assert isinstance(first, AuthoringResponse)
    assert isinstance(second, AuthoringResponse)
    assert first.data["receipt_id"] == second.data["receipt_id"]


@pytest.mark.service
@pytest.mark.asyncio
async def test_unknown_actor_token_is_typed_401(client: AuthoringClient) -> None:
    run_id = f"s17-{uuid.uuid4().hex[:8]}"
    with pytest.raises(AuthoringTransportError) as exc:
        await client.post_command(
            "/v1/sessions",
            "create_session",
            {"scope": "repo", "title": "denied"},
            idempotency_key=f"idk-deny-{run_id}",
            actor_token="unknown-bogus-token",
        )
    assert exc.value.is_actor_token_rejection
    assert not exc.value.is_machine_bearer_rejection
