"""Tests for the research_adr topology compilation.

The topology is compiled from the real ``vaultspec-adr-research`` preset with a
stub provider factory (FakeChatModel) and a fake proposal submitter, then driven
over a real ``AsyncSqliteSaver`` to its first document gate. No mocks of the
graph itself: the fan-out, synthesis join, inner review advance, and the gate
interrupt are all exercised.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from langchain_core.language_models.fake_chat_models import (
    FakeChatModel,
    FakeListChatModel,
)
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ..protocols import ProviderFactoryProtocol

from langchain_core.messages import AIMessage

from ...team.team_config import (
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from ...thread.errors import ConfigError
from ..compiler import _doc_review_router, compile_team_graph


def _review_state(review_text: str) -> dict[str, Any]:
    return {
        "active_agent": "review",
        "artifacts": [],
        "current_plan": [],
        "messages": [AIMessage(content=review_text, name="doc-reviewer")],
        "next": "",
        "thread_id": "review-thread",
        "token_usage": {},
    }


def test_doc_review_router_revises_on_exact_sentinel() -> None:
    router = _doc_review_router(writer_target="writer", gate_target="gate")
    text = "REVISION REQUIRED\n1. Frontmatter missing a date locator."
    assert router(_review_state(text)) == "writer"


def test_doc_review_router_advances_on_pass() -> None:
    router = _doc_review_router(writer_target="writer", gate_target="gate")
    assert router(_review_state("PASS")) == "gate"


def test_doc_review_router_no_false_positive_on_negated_prose() -> None:
    """Prose containing the word 'revision' must not route back to the writer."""
    router = _doc_review_router(writer_target="writer", gate_target="gate")
    text = "PASS\nThe locators are re-fetchable and no revision required is needed."
    assert router(_review_state(text)) == "gate"


class _FakeSubmitter:
    """Idempotent proposal submitter recording the phases it was asked to gate."""

    def __init__(self) -> None:
        self.phases: list[str] = []

    async def __call__(self, state: Any, phase: str) -> str:
        self.phases.append(phase)
        return f"prop-{phase}"


class _StateCapturingSubmitter:
    """Records the ``thread_id`` and message names the submit node observes.

    The production submitter both keys the run on ``state['thread_id']`` and
    sources the document body from the writer's ``synthesis``-named message
    (``_latest_document(state, "synthesis")``). Two invariants must hold at the
    submit node after the Send diverge / synthesis join: the thread id is the
    run's own (never a branch-scoped id), and the synthesis message actually
    reached the joined state (a checkpoint that carried only the seed messages
    with no synthesis message was the loose thread behind the empty-scaffold
    materialization). This submitter captures both so a regression can assert
    them.
    """

    def __init__(self) -> None:
        self.seen_thread_ids: list[str | None] = []
        self.seen_message_names: list[list[str]] = []

    async def __call__(self, state: Any, phase: str) -> str:
        self.seen_thread_ids.append(state.get("thread_id"))
        names = [getattr(m, "name", None) or "" for m in state.get("messages", [])]
        self.seen_message_names.append(names)
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
        "ground",
        "clarification",
        "research_dispatch",
        "research_dispatch_researcher_00",
        "research_dispatch_researcher_01",
        "synthesis",
        "research_review",
        "research_gate",
        "adr_author",
        "adr_review",
        "adr_gate",
        "plan_author",
        "plan_review",
        "plan_gate",
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
async def test_research_adr_missing_planner_role_raises(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """agent-flow ADR D4: the Plan phase's planner role is required, like adr-author."""
    team = _research_adr_team()
    trimmed = [w for w in team.workers if w.agent_id != "vaultspec-planner"]
    team = team.model_copy(update={"workers": trimmed})
    with pytest.raises(ConfigError, match="planner"):
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


@pytest.mark.asyncio
async def test_research_gate_submit_sees_run_state_and_synthesis_body(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """The gate submit sees the run thread id AND the synthesis message body.

    Regression for the diverge/synthesis state defect: the dispatch node fans
    the full state out to each researcher branch via ``Send`` and the branches
    join at synthesis, all under the same checkpointer thread. Two invariants
    must hold when ``research_submit`` runs:

    * ``state['thread_id']`` is the run's own id — the production submitter keys
      the engine session/changeset/proposal on it, so a branch-scoped id leaking
      back through the join would strand the parked run;
    * the synthesis-named message is present in the joined ``messages`` — the
      submitter sources the document body from it
      (``_latest_document(state, "synthesis")``), so if the Send/join dropped it
      the submit node would have no real body to propose (the empty-scaffold
      loose thread: a checkpoint carrying only the seed messages with no
      synthesis message).

    Drive the topology over a real checkpointer with per-thread research branches
    and assert both at the submit node.
    """
    submitter = _StateCapturingSubmitter()
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

    run_thread_id = "run-1784136458"
    state: dict[str, Any] = {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the phase machine.")],
        "next": "",
        "thread_id": run_thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }
    result = await graph.ainvoke(
        state, config={"configurable": {"thread_id": run_thread_id}}
    )

    assert "__interrupt__" in result
    # The submit node ran exactly once, and it saw the run's own thread id —
    # not "codebase"/"prior-art" (the research branch ids) nor any synthesis id.
    assert submitter.seen_thread_ids == [run_thread_id]
    # The synthesis writer's message reached the joined state the submit node
    # reads — the diverge/join did not drop it.
    assert submitter.seen_message_names, "submit node never ran"
    assert "synthesis" in submitter.seen_message_names[0], (
        "submit node did not see the synthesis message body in joined state; "
        f"names were {submitter.seen_message_names[0]}"
    )
    # The parked state still carries the run id verbatim.
    assert result["thread_id"] == run_thread_id


# ---------------------------------------------------------------------------
# P02.S06 -- the Plan third phase (agent-flow ADR D4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_phase_run_parks_at_gate_three_with_a_plan_proposal(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """The full run walks Gate 1 -> Gate 2 -> Gate 3, proposing all three phases.

    Approving Gate 1 (research) advances to the ADR phase; approving Gate 2 (adr)
    advances to the Plan phase (D4's new wiring: adr_gate's approved_target is
    plan_author, not END); the run then parks at Gate 3 with a plan proposal.
    """
    submitter = _FakeSubmitter()
    team = _research_adr_team([ResearchThreadSpec(thread_id="primary")])
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
    )

    thread_id = "three-phase-run"
    config = {"configurable": {"thread_id": thread_id}}
    state: dict[str, Any] = {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research, decide, and plan the feature.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }

    at_gate_one = await graph.ainvoke(state, config=config)
    assert at_gate_one["__interrupt__"][0].value["phase"] == "research"

    at_gate_two = await graph.ainvoke(
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )
    assert at_gate_two["__interrupt__"][0].value["phase"] == "adr"

    at_gate_three = await graph.ainvoke(
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )
    payload = at_gate_three["__interrupt__"][0].value
    assert payload["type"] == "document_approval_request"
    assert payload["phase"] == "plan"
    assert payload["proposal_id"] == "prop-plan"
    assert submitter.phases == ["research", "adr", "plan"]


@pytest.mark.asyncio
async def test_plan_gate_approve_completes_the_run(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Approving Gate 3 finishes the run (plan_gate's approved_target is END)."""
    submitter = _FakeSubmitter()
    team = _research_adr_team([ResearchThreadSpec(thread_id="primary")])
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
    )

    thread_id = "plan-gate-approve-run"
    config = {"configurable": {"thread_id": thread_id}}
    state: dict[str, Any] = {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research, decide, and plan the feature.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }

    await graph.ainvoke(state, config=config)  # -> parks at Gate 1 (research)
    await graph.ainvoke(  # approve Gate 1 -> parks at Gate 2 (adr)
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )
    await graph.ainvoke(  # approve Gate 2 -> parks at Gate 3 (plan)
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )
    final = await graph.ainvoke(  # approve Gate 3 -> END
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )

    assert "__interrupt__" not in final
    assert final["gate_phase"] == "plan"
    assert final["gate_verdict"] == "approved"
    assert submitter.phases == ["research", "adr", "plan"]


@pytest.mark.asyncio
async def test_plan_gate_request_changes_loops_a_revision(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """A request_changes verdict at Gate 3 routes back to plan_author and reproposes.

    Mirrors the proven research/adr phase-gate revision loop
    (``graph/tests/nodes/test_phase_gate.py``): the writer revises, the inner
    doc-review loop advances again (the stub model never emits REVISION
    REQUIRED), and the plan is resubmitted as a fresh proposal that parks the
    run at Gate 3 a second time.
    """
    submitter = _FakeSubmitter()
    team = _research_adr_team([ResearchThreadSpec(thread_id="primary")])
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
    )

    thread_id = "plan-gate-revision-run"
    config = {"configurable": {"thread_id": thread_id}}
    state: dict[str, Any] = {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research, decide, and plan the feature.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }

    await graph.ainvoke(state, config=config)
    await graph.ainvoke(
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )
    at_gate_three = await graph.ainvoke(
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )
    assert at_gate_three["__interrupt__"][0].value["phase"] == "plan"
    assert submitter.phases == ["research", "adr", "plan"]

    revised = await graph.ainvoke(
        Command(
            resume={
                "verdict": "request_changes",
                "notes": "Sequence the migration before the cutover.",
            }
        ),
        config=config,
    )

    # The revision loop re-ran the plan author and resubmitted: a second "plan"
    # proposal, and the run parks at Gate 3 again with the fresh proposal id.
    payload = revised["__interrupt__"][0].value
    assert payload["phase"] == "plan"
    assert payload["proposal_id"] == "prop-plan"


# ---------------------------------------------------------------------------
# S41 -- the ground stage wiring (agent-flow ADR D5 wiring)
# ---------------------------------------------------------------------------


_CLARIFY_RESPONSE = "\n".join(
    [
        "CLARIFICATION NEEDED",
        json.dumps(
            [
                {
                    "id": "provider",
                    "prompt": "Which provider should author the plan?",
                    "kind": "choice",
                    "options": ["codex", "zai"],
                    "required": True,
                }
            ]
        ),
    ]
)


class _RoleAwareProviderFactory:
    """Deterministic provider factory keying its response on the worker role.

    The researcher role's model is shared by the ground turn (one call) and
    every researcher fan-out branch (one call each), in that order — so a
    ``FakeListChatModel`` response LIST forces the ground turn to ask a
    clarifying question while every subsequent researcher call gets an
    innocuous response, deterministically and without live-model spend.
    """

    def __init__(self, *, researcher_responses: list[str]) -> None:
        self._researcher_responses = researcher_responses

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        role = getattr(agent_config, "role", None)
        if role == "researcher":
            return FakeListChatModel(responses=list(self._researcher_responses))
        return FakeChatModel(responses=["stub response"])


@pytest.mark.asyncio
async def test_ground_ready_proceeds_straight_to_diverge(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The default GROUND READY turn proceeds to research with no interrupt."""
    submitter = _FakeSubmitter()
    factory = _RoleAwareProviderFactory(
        researcher_responses=["GROUND READY", "a research finding"]
    )
    team = _research_adr_team([ResearchThreadSpec(thread_id="primary")])
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=factory,
        proposal_submitter=submitter,
    )

    thread_id = "ground-ready-run"
    state: dict[str, Any] = {
        "active_agent": "ground",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the phase machine.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }
    result = await graph.ainvoke(
        state, config={"configurable": {"thread_id": thread_id}}
    )

    # Reached the research gate directly - no clarification interrupt.
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["type"] == "document_approval_request"
    assert result.get("clarification_questions") is None


@pytest.mark.asyncio
async def test_ground_forces_clarification_then_resumes_to_research(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A forced CLARIFICATION NEEDED ground turn parks, then resumes to research.

    Deterministic-profile proof (no live-model spend) that the wiring the
    team lead ruled on actually reaches a park: FakeListChatModel forces the
    ground turn's response, so the flow is provable end to end rather than
    merely asserted as reachable code.
    """
    submitter = _FakeSubmitter()
    factory = _RoleAwareProviderFactory(
        researcher_responses=[_CLARIFY_RESPONSE, "a research finding"]
    )
    team = _research_adr_team([ResearchThreadSpec(thread_id="primary")])
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=factory,
        proposal_submitter=submitter,
    )

    thread_id = "ground-clarify-run"
    config = {"configurable": {"thread_id": thread_id}}
    state: dict[str, Any] = {
        "active_agent": "ground",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research it.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }

    parked = await graph.ainvoke(state, config=config)

    assert "__interrupt__" in parked
    payload = parked["__interrupt__"][0].value
    assert payload["type"] == "clarification_request"
    assert payload["questions"][0]["id"] == "provider"
    # The submit/dispatch machinery never ran - the run parked before diverge.
    assert submitter.phases == []

    resumed = await graph.ainvoke(
        Command(resume={"provider": "codex"}), config=config
    )

    # Answering rejoins at diverge and reaches the research gate normally.
    assert "__interrupt__" in resumed
    assert resumed["__interrupt__"][0].value["type"] == "document_approval_request"
    assert resumed["clarification_answers"] == {"provider": "codex"}
    threads = sorted(f["source_thread"] for f in resumed["research_findings"])
    assert threads == ["primary"]
    assert submitter.phases == ["research"]
