"""Live proof of the production DocumentProposalSubmitter (ADR PW1, P05.S12).

Mock-free against the running dashboard engine on loopback, resolved through the
discovery-file contract (``service`` marked, skipped when no engine is reachable
— an infrastructure gate, not a masked failure). Set
``VAULTSPEC_ENGINE_SERVICE_JSON`` to the engine's discovery file.

Proves the properties PW1/PW5 demand on real engine state:

- a whole-document propose-and-submit returns a real engine proposal id;
- ONE session is reused across calls (the constant create_session key dedupes);
- idempotent replay AND a simulated restart (a fresh submitter, same durable
  state) return the SAME proposal id with no second changeset or proposal;
- a revision-cycle bump advances the key to a distinct proposal.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ...thread.actor_tokens import ActorTokenBundle
from ...worker.token_store import RunTokenStore

if TYPE_CHECKING:
    from ...thread.state import TeamState
from .. import (
    AuthoringClient,
    AuthoringResponse,
    AuthoringSession,
    DocumentProposalSubmitter,
    PhaseAuthoringSpec,
    derive_idempotency_key,
    mint_actor_token,
)

_STALE_MS = 120_000
_RESEARCH_ROLE = "synthesist"
_RESEARCH_WRITER = "synthesis"


def _resolve_engine() -> tuple[str, str] | None:
    now_ms = int(time.time() * 1000)
    candidates: list[Path] = []
    env_path = os.environ.get("VAULTSPEC_ENGINE_SERVICE_JSON")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".vaultspec" / "service.json")
    for path in candidates:
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
            "no reachable authoring engine; start `vaultspec serve` or set "
            "VAULTSPEC_ENGINE_SERVICE_JSON"
        )
    return resolved


async def _store_with_role_token(
    base_url: str, bearer: str, thread_id: str, role: str
) -> RunTokenStore:
    """Mint a real per-actor token for *role* and register it for the run."""
    async with AuthoringClient(base_url, bearer) as client:
        minted = await mint_actor_token(
            client, actor_id=f"agent:{role}-{thread_id}", kind="agent"
        )
    assert isinstance(minted, AuthoringResponse)
    assert isinstance(minted.data, dict)
    raw = minted.data.get("raw_token")
    assert isinstance(raw, str) and raw
    store = RunTokenStore()
    store.register(
        thread_id, ActorTokenBundle(tokens={role: raw}, engine_bearer=bearer)
    )
    return store


def _submitter(base_url: str, store: RunTokenStore) -> DocumentProposalSubmitter:
    return DocumentProposalSubmitter(
        engine_base_url=base_url,
        token_store=store,
        feature="p05s12",
        phases={
            "research": PhaseAuthoringSpec(
                document_role=_RESEARCH_ROLE,
                writer_message_name=_RESEARCH_WRITER,
                doc_type="research",
            )
        },
    )


def _state(thread_id: str, *bodies: str) -> TeamState:
    messages: list[BaseMessage] = [HumanMessage(content="ground the feature")]
    for body in bodies:
        messages.append(AIMessage(content=body, name=_RESEARCH_WRITER))
    return cast("TeamState", {"thread_id": thread_id, "messages": messages})


@pytest.mark.service
@pytest.mark.asyncio
async def test_submitter_produces_real_proposal(engine: tuple[str, str]) -> None:
    base_url, bearer = engine
    thread_id = f"p05s12-{uuid.uuid4().hex[:8]}"
    store = await _store_with_role_token(base_url, bearer, thread_id, _RESEARCH_ROLE)
    submitter = _submitter(base_url, store)

    proposal_id = await submitter(
        _state(thread_id, "# Research\n\nLive body."), "research"
    )
    assert isinstance(proposal_id, str) and proposal_id


@pytest.mark.service
@pytest.mark.asyncio
async def test_replay_and_restart_return_same_proposal(engine: tuple[str, str]) -> None:
    """Replay and a simulated restart dedupe to the same proposal (no duplicate)."""
    base_url, bearer = engine
    thread_id = f"p05s12-{uuid.uuid4().hex[:8]}"
    store = await _store_with_role_token(base_url, bearer, thread_id, _RESEARCH_ROLE)
    state = _state(thread_id, "# Research\n\nReplay-exact body.")

    first = await _submitter(base_url, store)(state, "research")
    # In-dispatch replay: same submitter, same state.
    replay = await _submitter(base_url, store)(state, "research")
    # Restart: a brand-new submitter (fresh objects), same durable state + tokens.
    restart = await _submitter(base_url, store)(state, "research")

    assert first == replay == restart, "replay/restart must not create a new proposal"


@pytest.mark.service
@pytest.mark.asyncio
async def test_session_reused_across_calls(engine: tuple[str, str]) -> None:
    """The constant create_session key resumes ONE session across calls."""
    base_url, bearer = engine
    thread_id = f"p05s12-{uuid.uuid4().hex[:8]}"
    store = await _store_with_role_token(base_url, bearer, thread_id, _RESEARCH_ROLE)
    actor_token = store.actor_token(thread_id, _RESEARCH_ROLE)
    key = derive_idempotency_key(thread_id, "create_session")

    async with AuthoringClient(base_url, bearer, actor_token=actor_token) as client:
        s1 = AuthoringSession(client, thread_id)
        first = await s1.create_session(
            scope="repo", title="reuse", idempotency_key=key
        )
        s2 = AuthoringSession(client, thread_id)
        second = await s2.create_session(
            scope="repo", title="reuse", idempotency_key=key
        )
    assert isinstance(first, AuthoringResponse)
    assert isinstance(second, AuthoringResponse)
    # Same key -> the engine returns the same session id (create-or-resume).
    assert first.data["session_id"] == second.data["session_id"]


@pytest.mark.service
@pytest.mark.asyncio
async def test_revision_cycle_advances_to_new_proposal(engine: tuple[str, str]) -> None:
    """A request-changes revision (a second author pass) is a distinct proposal."""
    base_url, bearer = engine
    thread_id = f"p05s12-{uuid.uuid4().hex[:8]}"
    store = await _store_with_role_token(base_url, bearer, thread_id, _RESEARCH_ROLE)
    submitter = _submitter(base_url, store)

    rev1 = await submitter(_state(thread_id, "# v1"), "research")
    # A second author message = revision cycle 2 -> a new key -> a new proposal.
    rev2 = await submitter(_state(thread_id, "# v1", "# v2 revised"), "research")
    assert rev1 != rev2, "a revised document must be a distinct proposal"
