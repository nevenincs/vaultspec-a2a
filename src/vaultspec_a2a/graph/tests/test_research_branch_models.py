"""Parallel research branches each run on a model of their own.

The research fan-out runs every branch in one superstep, so the branches'
model turns overlap. A provider model owns one provider session and refuses a
second concurrent turn rather than interleave two conversations on one
transport. Branches that shared the one researcher model resolved at compile
time therefore failed as soon as a fan-out had two branches on a real lane;
in-process scripted models, which accept concurrent calls, never showed it.

The models here are production ``AcpChatModel`` instances driving the real ACP
transport over real subprocesses; only the agent at the far end of the pipe is
the repository's ACP simulator.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...authoring.submitter import DocumentProposalSubmitter
from ...team.team_config import ResearchThreadSpec, load_agent_config, load_team_config
from ...worker.token_store import RunTokenStore
from ..compiler import compile_team_graph, researcher_node_name
from .conftest import deterministic_model_assignment

SIMULATOR_PATH = Path(__file__).parent / "acp_simulator.py"

_PRESET = "vaultspec-adr-research-mock"
_DISPATCH = "research_dispatch"
_THREADS = [
    ResearchThreadSpec(thread_id="codebase"),
    ResearchThreadSpec(thread_id="prior-art"),
    ResearchThreadSpec(thread_id="operations"),
]


class _SimulatorProviderFactory:
    """A real provider factory handing out production ACP models."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.created: list[tuple[str | None, Any]] = []

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Path | None = None,
        **kwargs: Any,
    ) -> Any:
        from ...providers.acp_chat_model import AcpChatModel

        instance = AcpChatModel(
            command=[sys.executable, str(SIMULATOR_PATH), "--response", "finding"],
            env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},
            workspace_root=str(self.workspace_root),
        )
        self.created.append((getattr(agent_config, "role", None), instance))
        return instance


def _team() -> Any:
    team = load_team_config(_PRESET)
    topology = team.topology.model_copy(update={"research_threads": _THREADS})
    return team.model_copy(update={"topology": topology})


@pytest.mark.asyncio
async def test_every_parallel_research_branch_completes_its_own_turn(
    tmp_path: Path,
) -> None:
    team = _team()
    factory = _SimulatorProviderFactory(tmp_path)
    branches = {researcher_node_name(_DISPATCH, i) for i in range(len(_THREADS))}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        # The protocol declares invoke only; the drive streams to stop at the join.
        graph: Any = compile_team_graph(
            team_config=team,
            agent_configs={
                w.agent_id: load_agent_config(w.agent_id) for w in team.workers
            },
            checkpointer=saver,
            provider_factory=factory,
            autonomous=True,
            workspace_root=tmp_path,
            step_timeout=60.0,
            # Never reached: the drive stops once the fan-out has joined.
            proposal_submitter=DocumentProposalSubmitter(
                engine_base_url="http://127.0.0.1:9",
                token_store=RunTokenStore(),
                phases={},
                workspace_root=tmp_path,
            ),
            model_assignment=deterministic_model_assignment(team),
        )
        finished: set[str] = set()
        config = {"configurable": {"thread_id": "branches"}, "recursion_limit": 20}
        async for update in graph.astream(
            {
                "active_agent": "",
                "artifacts": [],
                "current_plan": [],
                "messages": [HumanMessage(content="Research the cache design.")],
                "next": "",
                "thread_id": "branches",
                "token_usage": {},
            },
            config=config,
        ):
            finished |= branches & update.keys()
            if finished == branches:
                break

    assert finished == branches
    researcher_models = [m for role, m in factory.created if role == "researcher"]
    assert len({id(m) for m in researcher_models}) == len(_THREADS)
