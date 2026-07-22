"""Live boundary proof: the research_adr writer grounds on a real feedback batch.

Test-integrity / wire-contract (S14): ONLINE against the real engine resolved via
the discovery file, never a mocked wire. It proves the end-to-end grounding path
the offline tests cannot reach: a REAL feedback batch created on the engine, a
REAL FeedbackContextReader that retrieves it by id under a REAL minted actor
token, and the actual synthesist worker node - which, when feedback_batch_id is in
graph state, must hand its model a "Reviewer feedback to address" SystemMessage
carrying the batch's comments. The model is a recording BaseChatModel (the
established graph-boundary pattern) so the assertion is exactly what the writer
receives; everything upstream of it is real.

``service``-marked and skipped without a reachable engine (an infrastructure gate,
not a masked failure). Set VAULTSPEC_ENGINE_SERVICE_JSON to the engine's discovery
file.
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
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from vaultspec_a2a.authoring import FeedbackContextReader
from vaultspec_a2a.graph.nodes.worker import create_worker_node
from vaultspec_a2a.thread.actor_tokens import ActorTokenBundle
from vaultspec_a2a.worker.token_store import RunTokenStore

_STALE_MS = 120_000
_SYNTHESIST = "vaultspec-synthesist"


def _resolve_engine() -> tuple[str, str] | None:
    """Resolve a live engine (base_url, bearer) via the discovery contract."""
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
        port, token = info.get("port"), info.get("service_token")
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


class _RecordingModel(BaseChatModel):
    """A model that records the message list the node hands it, then answers."""

    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    @property
    def _llm_type(self) -> str:
        return "recording-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("async only")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._calls.append(list(messages))
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="revised"))]
        )


@pytest.fixture(scope="module")
def engine() -> tuple[str, str]:
    resolved = _resolve_engine()
    if resolved is None:
        pytest.skip(
            "no reachable authoring engine; start `vaultspec serve` or set "
            "VAULTSPEC_ENGINE_SERVICE_JSON"
        )
    return resolved


def _post(base: str, path: str, bearer: str, actor: str | None, body: dict) -> dict:
    headers = {"Authorization": f"Bearer {bearer}", "content-type": "application/json"}
    if actor is not None:
        headers["x-authoring-actor-token"] = actor
    resp = httpx.post(f"{base}{path}", headers=headers, json=body, timeout=10.0)
    resp.raise_for_status()
    return resp.json()["data"]


@pytest.mark.service
@pytest.mark.asyncio
async def test_synthesist_node_grounds_on_a_real_feedback_batch(
    engine: tuple[str, str],
) -> None:
    base, bearer = engine
    run_id = f"s14-{uuid.uuid4().hex[:8]}"

    # Mint a real synthesist actor token and open a session.
    minted = _post(
        base,
        "/authoring/v1/actor-tokens",
        bearer,
        None,
        {"actor": {"id": f"agent:{_SYNTHESIST}-{run_id}", "kind": "agent"}},
    )
    actor_token = minted["raw_token"]
    session = _post(
        base,
        "/authoring/v1/sessions",
        bearer,
        actor_token,
        {
            "api_version": "v1",
            "command": "create_session",
            "idempotency_key": f"s-{run_id}",
            "payload": {"scope": "repo", "title": f"S14 {run_id}"},
        },
    )
    session_id = session["session_id"]

    # Freeze a real feedback batch the writer must revise against.
    created = _post(
        base,
        "/authoring/v1/feedback-batches",
        bearer,
        actor_token,
        {
            "api_version": "v1",
            "command": "create_feedback_batch",
            "idempotency_key": f"b-{run_id}",
            "payload": {
                "session_id": session_id,
                "source_document": f"node:doc-{run_id}",
                "source_revision": f"blob-{run_id}",
                "items": [
                    {
                        "comment_id": f"c1-{run_id}",
                        "body": "expand the risk analysis",
                        "anchor": {
                            "heading_path": ["Risks"],
                            "content_start": 0,
                            "content_end": 3,
                        },
                    }
                ],
            },
        },
    )
    batch_id = created["batch_id"]

    # Real token store + reader, exactly as the worker builds them at run start.
    token_store = RunTokenStore()
    token_store.register(
        run_id,
        ActorTokenBundle(tokens={_SYNTHESIST: actor_token}, engine_bearer=bearer),
    )
    reader = FeedbackContextReader(
        engine_base_url=base, token_store=token_store, read_role=_SYNTHESIST
    )

    recording = _RecordingModel()
    node = create_worker_node(
        model=recording,
        system_prompt="You are the synthesist.",
        name="synthesis",
        role="synthesist",
        feedback_reader=reader,
    )

    state: Any = {
        "messages": [HumanMessage(content="Revise the research document.")],
        "active_agent": _SYNTHESIST,
        "artifacts": [],
        "current_plan": [],
        "thread_id": run_id,
        "token_usage": {},
        "next": "",
        "active_feature": "edge-feature",
        "feedback_batch_id": batch_id,
    }
    await node(state)

    # The writer's model received the reviewer feedback, retrieved live by id.
    assert recording.calls, "the node never invoked the model"
    system_text = "\n".join(
        str(m.content) for m in recording.calls[0] if m.type == "system"
    )
    assert "Reviewer feedback to address" in system_text
    assert "Risks: expand the risk analysis" in system_text


@pytest.mark.service
@pytest.mark.asyncio
async def test_synthesist_node_ungrounded_without_a_batch(
    engine: tuple[str, str],
) -> None:
    """No feedback_batch_id in state -> no grounding block (zero behaviour change)."""
    base, _bearer = engine
    token_store = RunTokenStore()
    reader = FeedbackContextReader(
        engine_base_url=base, token_store=token_store, read_role=_SYNTHESIST
    )
    recording = _RecordingModel()
    node = create_worker_node(
        model=recording,
        system_prompt="You are the synthesist.",
        name="synthesis",
        role="synthesist",
        feedback_reader=reader,
    )
    state: Any = {
        "messages": [HumanMessage(content="Draft the research document.")],
        "active_agent": _SYNTHESIST,
        "artifacts": [],
        "current_plan": [],
        "thread_id": f"s14-none-{uuid.uuid4().hex[:8]}",
        "token_usage": {},
        "next": "",
        "active_feature": "edge-feature",
    }
    await node(state)
    assert recording.calls
    system_text = "\n".join(
        str(m.content) for m in recording.calls[0] if m.type == "system"
    )
    assert "Reviewer feedback to address" not in system_text
