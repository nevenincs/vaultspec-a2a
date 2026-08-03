"""Live receipt proof for document-role conventions and invocation config.

The compiled ``research_adr`` graph is exercised through its public
``ainvoke`` boundary.  A passive LangChain callback observes the prompts that
the real deterministic provider receives; it does not replace a graph node,
provider, or proposal submitter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import TypeAdapter

from ..authoring import (
    AuthoringClient,
    AuthoringResponse,
    DocumentProposalSubmitter,
    PhaseAuthoringSpec,
    mint_actor_token,
)
from ..graph.compiler import compile_team_graph
from ..providers.factory import ProviderFactory
from ..team import load_agent_config, load_team_config
from ..thread.actor_tokens import ActorTokenBundle
from ..worker.token_store import RunTokenStore

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from ..authoring.discovery import EngineEndpoint
    from ..thread.state import TeamState

_CONVENTIONS_MARKER = "Emission mechanics"
_WORKER_RULES_HEADER = "Project Coding Rules & Guidelines"
_RESEARCH_ADR_PRESET = "vaultspec-adr-research-deterministic"


@dataclass
class _PromptReceipt(BaseCallbackHandler):
    """Passively retain model prompts observed through RunnableConfig callbacks."""

    calls: list[list[BaseMessage]] = field(default_factory=list)

    @override
    def on_chat_model_start(
        self,
        serialized: dict[str, object],
        messages: list[list[BaseMessage]],
        **kwargs: object,
    ) -> None:
        del serialized, kwargs
        self.calls.extend(list(call) for call in messages)


def _raw_actor_token(response: AuthoringResponse) -> str:
    """Read the engine's untyped envelope without propagating unknown data."""
    payload = TypeAdapter(dict[str, object]).validate_python(response.data)
    raw_token = payload.get("raw_token")
    assert isinstance(raw_token, str) and raw_token
    return raw_token


def _production_phase_specs() -> dict[str, PhaseAuthoringSpec]:
    """The phase specifications used by the production graph lifecycle."""
    return {
        "research": PhaseAuthoringSpec(
            document_role="vaultspec-synthesist",
            writer_message_name="synthesis",
            doc_type="research",
            completion_sentinel="RESEARCH READY",
        ),
        "adr": PhaseAuthoringSpec(
            document_role="vaultspec-adr-author",
            writer_message_name="adr_author",
            doc_type="adr",
            completion_sentinel="ADR READY",
        ),
        "plan": PhaseAuthoringSpec(
            document_role="vaultspec-plan-author",
            writer_message_name="plan_author",
            doc_type="plan",
            completion_sentinel="PLAN READY",
        ),
    }


async def _live_token_store(
    base_url: str,
    bearer: str,
    thread_id: str,
    phase_specs: dict[str, PhaseAuthoringSpec],
) -> RunTokenStore:
    """Register genuine engine actor tokens for every production document role."""
    tokens: dict[str, str] = {}
    async with AuthoringClient(base_url, bearer) as client:
        for spec in phase_specs.values():
            minted = await mint_actor_token(
                client,
                actor_id=f"agent:{spec.document_role}-{thread_id}",
                kind="agent",
            )
            assert isinstance(minted, AuthoringResponse)
            tokens[spec.document_role] = _raw_actor_token(minted)
    store = RunTokenStore()
    store.register(thread_id, ActorTokenBundle(tokens=tokens, engine_bearer=bearer))
    return store


def _frozen_deterministic_assignment(agent_ids: list[str]) -> dict[str, dict[str, str]]:
    """Pin every preset worker to the real in-process deterministic provider."""
    return {
        agent_id: {
            "provider": "deterministic",
            "model_name": "deterministic",
        }
        for agent_id in agent_ids
    }


def _document_state(thread_id: str, feature: str, workspace_root: str) -> TeamState:
    return {
        "active_agent": "researcher",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the receipt contract.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": feature,
        "workspace_root": workspace_root,
        "token_usage": {},
    }


def _system_texts(calls: list[list[BaseMessage]]) -> list[str]:
    return [
        message.content
        for call in calls
        for message in call
        if isinstance(message, SystemMessage) and isinstance(message.content, str)
    ]


@pytest.mark.service
@pytest.mark.asyncio
async def test_compiled_document_graph_receives_conventions_via_runtime_config(
    live_engine: EngineEndpoint,
    tmp_path: Path,
) -> None:
    """A real graph run delivers config callbacks to research and writer models."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert not (workspace / ".vaultspec" / "rules").exists()

    thread_id = f"receipt-{uuid.uuid4().hex[:8]}"
    feature = f"receipt-{uuid.uuid4().hex[:8]}"
    phase_specs = _production_phase_specs()
    token_store = await _live_token_store(
        live_engine.base_url,
        live_engine.bearer_token,
        thread_id,
        phase_specs,
    )
    proposal_submitter = DocumentProposalSubmitter(
        engine_base_url=live_engine.base_url,
        token_store=token_store,
        phases=phase_specs,
        workspace_root=workspace,
    )
    team = load_team_config(_RESEARCH_ADR_PRESET)
    agent_configs = {
        worker.agent_id: load_agent_config(worker.agent_id) for worker in team.workers
    }
    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        provider_factory=ProviderFactory(),
        checkpointer=InMemorySaver(),
        workspace_root=workspace,
        feature_tag=feature,
        proposal_submitter=proposal_submitter,
        model_assignment=_frozen_deterministic_assignment(list(agent_configs)),
    )
    receipt = _PromptReceipt()
    config: RunnableConfig = {
        "callbacks": [receipt],
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 32,
    }

    result = await graph.ainvoke(
        _document_state(thread_id, feature, str(workspace)), config=config
    )

    assert result
    system_texts = _system_texts(receipt.calls)
    assert system_texts, "the configured callback did not observe a model prompt"
    assert any(_CONVENTIONS_MARKER in text for text in system_texts), (
        "an executing document role did not receive the bundled conventions"
    )
    assert any(_WORKER_RULES_HEADER in text for text in system_texts), (
        "worker rules were not present at the observed model boundary"
    )
