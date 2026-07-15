"""Tests for the research_adr topology compilation (P02.S06).

The topology is compiled from the real ``vaultspec-adr-research`` preset with a
stub provider factory (FakeChatModel) and a fake proposal submitter, then driven
over a real ``AsyncSqliteSaver`` to its first document gate. No mocks of the
graph itself: the fan-out, synthesis join, inner review advance, and the gate
interrupt are all exercised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ..protocols import ProviderFactoryProtocol

from vaultspec_a2a.team.team_config import (
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from vaultspec_a2a.thread.errors import ConfigError

from ..compiler import compile_team_graph


class _FakeSubmitter:
    """Idempotent proposal submitter recording the phases it was asked to gate."""

    def __init__(self) -> None:
        self.phases: list[str] = []

    async def __call__(self, state: Any, phase: str) -> str:
        self.phases.append(phase)
        return f"prop-{phase}"


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _research_adr_team(research_threads: list[ResearchThreadSpec] | None = None) -> Any:
    team = load_team_config("vaultspec-adr-research")
    if research_threads is not None:
        topo = team.topology.model_copy(update={"research_threads": research_threads})
        team = team.model_copy(update={"topology": topo})
    return team


def _agent_configs(team: Any) -> dict[str, Any]:
    return {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}


@pytest.mark.asyncio
async def test_research_adr_compiles_expected_node_set(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    team = _research_adr_team(
        [
            ResearchThreadSpec(thread_id="codebase"),
            ResearchThreadSpec(thread_id="prior-art"),
        ]
    )
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=_FakeSubmitter(),
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert {
        "research_dispatch",
        "research_dispatch_researcher_00",
        "research_dispatch_researcher_01",
        "synthesis",
        "research_review",
        "research_gate",
        "adr_author",
        "adr_review",
        "adr_gate",
    } <= node_keys
    assert list(graph.interrupt_before_nodes) == []


@pytest.mark.asyncio
async def test_research_adr_requires_proposal_submitter(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    team = _research_adr_team()
    with pytest.raises(ConfigError, match="proposal_submitter"):
        compile_team_graph(
            team_config=team,
            agent_configs=_agent_configs(team),
            checkpointer=checkpointer,
            provider_factory=pf,
            proposal_submitter=None,
        )


@pytest.mark.asyncio
async def test_research_adr_missing_role_raises(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    team = _research_adr_team()
    # Drop the adr-author worker so a required role is unresolved.
    trimmed = [w for w in team.workers if w.agent_id != "vaultspec-adr-author"]
    team = team.model_copy(update={"workers": trimmed})
    with pytest.raises(ConfigError, match="adr-author"):
        compile_team_graph(
            team_config=team,
            agent_configs=_agent_configs(team),
            checkpointer=checkpointer,
            provider_factory=pf,
            proposal_submitter=_FakeSubmitter(),
        )


@pytest.mark.asyncio
async def test_research_adr_runs_to_first_document_gate(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """The machine fans out, synthesises, passes review, and parks at gate one.

    The stub models return no ``REVISION`` sentinel, so the inner review loop
    advances; the research gate then proposes+submits and interrupts for the
    human verdict.
    """
    submitter = _FakeSubmitter()
    team = _research_adr_team(
        [
            ResearchThreadSpec(thread_id="codebase"),
            ResearchThreadSpec(thread_id="prior-art"),
        ]
    )
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
    )

    state: dict[str, Any] = {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the phase machine.")],
        "next": "",
        "thread_id": "ra-thread",
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }
    result = await graph.ainvoke(
        state, config={"configurable": {"thread_id": "ra-run"}}
    )

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "document_approval_request"
    assert payload["phase"] == "research"
    assert payload["proposal_id"] == "prop-research"
    # The diverge stage accumulated one finding per configured thread.
    threads = sorted(f["source_thread"] for f in result["research_findings"])
    assert threads == ["codebase", "prior-art"]
    assert submitter.phases == ["research"]
