"""The supervisor gates on the vault as it is now, not as it was last turn.

The phase gates read ``vault_index``, and the only refresh used to happen in
the mount node - which runs AFTER a routing decision, on the way into the
worker. So a document a worker had just written was invisible to the very
decision that had to see it, and the run was told the artifact was missing
while it sat on disk.

Driven against a real workspace: the writer worker writes a real file into a
real ``.vault/`` tree and the compiled star graph is run over a real
checkpointer, so the refresh is exercised as a filesystem read rather than
described.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, override

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from ...team.team_config import (
    TeamConfig,
    TeamGraphConfig,
    TopologyConfig,
    TopologyType,
    WorkerRef,
    load_agent_config,
)
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ..compiler import compile_team_graph
from .conftest import deterministic_model_assignment

if TYPE_CHECKING:
    from pathlib import Path

_PLAN_AUTHOR = "vaultspec-plan-author"
_CODER = "vaultspec-coder"
_FEATURE = "index-refresh"


class _PlanWritingChat(BaseChatModel):
    """A writer whose turn really does put a plan document on disk."""

    plan_path: Any = None

    @property
    @override
    def _llm_type(self) -> str:
        return "plan-writing"

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        path = cast("Path", self.plan_path)
        path.write_text("# plan\n", encoding="utf-8")
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="plan written"))]
        )


class _RoutingChat(BaseChatModel):
    """Names each route in turn; the last reply repeats once exhausted."""

    replies: Any = None

    @property
    @override
    def _llm_type(self) -> str:
        return "routing"

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        queued = cast("list[str]", self.replies)
        reply = queued.pop(0) if len(queued) > 1 else queued[0]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=reply))]
        )


class _Factory:
    """Supervisor routes; the plan author writes; everyone else reports back."""

    def __init__(self, plan_path: Path, replies: list[str]) -> None:
        self._plan_path = plan_path
        self._replies = replies

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del provider, model, workspace_root, kwargs
        agent_id = getattr(agent_config, "id", None)
        if agent_id is None:
            return _RoutingChat(replies=self._replies)
        if agent_id == _PLAN_AUTHOR:
            return _PlanWritingChat(plan_path=self._plan_path)
        return _RoutingChat(replies=[f"{agent_id} did its part"])


def _run_input(thread_id: str, prompt: str) -> dict[str, Any]:
    # The completion node this topology ends at applies the dispatch receipt,
    # so a run that reaches the end needs a real one seeded.
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=thread_id,
        action_id="ingest",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint({"run": thread_id}),
        dispatch_id="ingest",
        run_revision=1,
        writer_generation=1,
    ).model_dump(mode="json")
    return {
        "messages": [HumanMessage(content=prompt)],
        "thread_id": thread_id,
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "next": "",
        "active_feature": _FEATURE,
        "vault_index": {},
        "active_graph_action_receipt": receipt,
        "graph_action_receipts": {"ingest": receipt},
    }


def _star_team() -> TeamConfig:
    return TeamConfig(
        id="index-refresh-star",
        display_name="index-refresh-star",
        topology=TopologyConfig(type=TopologyType.STAR),
        graph=TeamGraphConfig(step_timeout_seconds=120),
        workers=[WorkerRef(agent_id=_PLAN_AUTHOR), WorkerRef(agent_id=_CODER)],
    )


@pytest.mark.asyncio
async def test_the_supervisor_gates_on_a_plan_its_own_worker_just_wrote(
    tmp_path: Path,
) -> None:
    """The exec route is admitted on the pass after the plan lands on disk.

    Without the refresh this decision was refused by the HARD exec gate - the
    index it read was the one from before the plan author ran - and the run
    burned its re-ask budget being told to produce a plan it already had.
    """
    vault = tmp_path / ".vault"
    (vault / "adr").mkdir(parents=True)
    (vault / "plan").mkdir(parents=True)
    adr = vault / "adr" / f"2026-09-30-{_FEATURE}-adr.md"
    adr.write_text("# adr\n", encoding="utf-8")
    plan_path = vault / "plan" / f"2026-09-30-{_FEATURE}-plan.md"

    team = _star_team()
    graph: Any = compile_team_graph(
        team_config=team,
        agent_configs={a: load_agent_config(a) for a in (_PLAN_AUTHOR, _CODER)},
        provider_factory=_Factory(plan_path, [_PLAN_AUTHOR, _CODER, "FINISH"]),
        model_assignment=deterministic_model_assignment(team),
        checkpointer=InMemorySaver(),
        workspace_root=tmp_path,
        # No human in this run: the subject is the index the gate reads, not
        # the approval interrupt an exec route would otherwise raise.
        autonomous=True,
    )

    thread: Any = {"configurable": {"thread_id": "index-refresh"}}
    visited: list[str] = []
    async for update in graph.astream(
        _run_input("index-refresh", "Carry the feature forward."),
        thread,
        stream_mode="updates",
    ):
        visited.extend(cast("dict[str, Any]", update))

    assert plan_path.exists(), "the plan author never wrote its document"
    # The exec worker ran, so the gate admitted the route rather than refusing
    # it for a plan that was already on disk.
    assert _CODER in visited
    settled = await graph.aget_state(thread)
    assert settled.values["supervisor_reasks"] == 0
    assert settled.values["routing_error"] is None
    # The decision's own view of the vault is what the run kept.
    assert (
        f".vault/plan/2026-09-30-{_FEATURE}-plan.md"
        in settled.values["vault_index"]["plan"]
    )


@pytest.mark.asyncio
async def test_the_first_supervisor_pass_sees_a_vault_it_was_not_seeded_with(
    tmp_path: Path,
) -> None:
    """A run seeded with no index still gates on what the vault holds.

    The entry edge goes straight to the supervisor with no mount node in
    front of it, so before this the very first decision of a run could only
    see the index its dispatch happened to carry.
    """
    vault = tmp_path / ".vault"
    (vault / "adr").mkdir(parents=True)
    (vault / "plan").mkdir(parents=True)
    (vault / "adr" / f"2026-09-30-{_FEATURE}-adr.md").write_text("# adr\n")

    team = _star_team()
    graph: Any = compile_team_graph(
        team_config=team,
        agent_configs={a: load_agent_config(a) for a in (_PLAN_AUTHOR, _CODER)},
        provider_factory=_Factory(
            vault / "plan" / "unused.md", [_PLAN_AUTHOR, "FINISH"]
        ),
        model_assignment=deterministic_model_assignment(team),
        checkpointer=InMemorySaver(),
        workspace_root=tmp_path,
        autonomous=True,
    )

    thread: Any = {"configurable": {"thread_id": "first-pass"}}
    first = await graph.ainvoke(_run_input("first-pass", "Plan the feature."), thread)

    # The plan phase needs an ADR, and the only evidence of one is on disk.
    assert first["vault_index"]["adr"] == [f".vault/adr/2026-09-30-{_FEATURE}-adr.md"]
    assert first["supervisor_reasks"] == 0
