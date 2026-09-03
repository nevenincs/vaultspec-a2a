"""Tests for the research_adr topology compilation.

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
from langgraph.types import Command

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.runnables import RunnableConfig

    from ..protocols import ProviderFactoryProtocol

from langchain_core.messages import AIMessage

from ...streaming.node_metadata import node_metadata_from_graph
from ...team.team_config import (
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from ...thread.errors import ConfigError
from ..compiler import _doc_review_router, compile_team_graph
from .conftest import deterministic_model_assignment


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
        model_assignment=deterministic_model_assignment(team),
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
        "plan_author",
        "plan_review",
        "plan_gate",
    } <= node_keys
    assert list(graph.interrupt_before_nodes) == []


@pytest.mark.asyncio
async def test_research_adr_discloses_one_metadata_entry_per_worker(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """A compiled research_adr graph must disclose its whole roster, not none.

    ``node_metadata_from_graph`` - the real function every disclosure surface
    (``/team/status``, the ``team_status`` broadcast, the run snapshot) walks -
    SKIPS a node whose metadata is empty. Every research_adr worker node used
    to be added with no ``metadata=`` at all, so this topology reported an
    empty roster while executing a full one; nothing else catches that, since
    it type-checks clean and every node still runs. Pinned here against the
    real frozen-catalog compile path, not inferred from types.
    """
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
        model_assignment=deterministic_model_assignment(team),
    )

    disclosed = node_metadata_from_graph(graph)
    expected_worker_nodes = {
        "research_dispatch_researcher_00",
        "research_dispatch_researcher_01",
        "synthesis",
        "research_review",
        "adr_author",
        "adr_review",
        "plan_author",
        "plan_review",
    }
    # This is the assertion that fails without the fix: node_metadata_from_graph
    # SKIPS a node whose metadata dict is empty, and every one of these used to
    # be added with no metadata= at all - the whole roster was absent, not just
    # short a field.
    assert expected_worker_nodes <= set(disclosed), disclosed

    for node_name in expected_worker_nodes:
        entry = disclosed[node_name]
        assert entry["provider"] == "deterministic", (node_name, entry)
        assert entry["display_name"], (node_name, entry)
        assert entry["role"], (node_name, entry)


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
            model_assignment=deterministic_model_assignment(team),
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
            model_assignment=deterministic_model_assignment(team),
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
        model_assignment=deterministic_model_assignment(team),
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
        model_assignment=deterministic_model_assignment(team),
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


@pytest.mark.asyncio
async def test_plan_phase_runs_after_gate_two_and_parks_on_gate_three(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Approving both document gates advances into Plan and parks on gate three.

    Drives the REAL compiled topology over a real ``AsyncSqliteSaver``, resuming
    each interrupt by ``Command`` exactly as the verdict subscriber does. Nothing
    about the phase machine is simulated: the run fans out, synthesizes, passes the
    inner review, parks at gate one; an approved verdict advances it to the ADR
    writer, which parks at gate two; a second approved verdict must advance it into
    the PLAN writer and park it at gate three. The submitter's recorded phase
    sequence is the proof that the plan phase is a real third stage behind gate
    two, not an alias of the ADR stage.
    """
    submitter = _FakeSubmitter()
    team = _research_adr_team([ResearchThreadSpec(thread_id="codebase")])
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
        model_assignment=deterministic_model_assignment(team),
    )

    run_thread_id = "ra-plan-run"
    config: RunnableConfig = {"configurable": {"thread_id": run_thread_id}}
    state: dict[str, Any] = {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research and plan the phase machine.")],
        "next": "",
        "thread_id": run_thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }

    parked_at_research = await graph.ainvoke(state, config=config)
    assert parked_at_research["__interrupt__"][0].value["phase"] == "research"

    approve = Command[str](resume={"verdict": "approved", "notes": None})
    parked_at_adr = await graph.ainvoke(approve, config=config)
    assert parked_at_adr["__interrupt__"][0].value["phase"] == "adr"

    parked_at_plan = await graph.ainvoke(approve, config=config)
    plan_payload = parked_at_plan["__interrupt__"][0].value
    assert plan_payload["type"] == "document_approval_request"
    assert plan_payload["phase"] == "plan"
    assert plan_payload["proposal_id"] == "prop-plan"

    # Three phases submitted, in the ADR-mandated order, each exactly once.
    assert submitter.phases == ["research", "adr", "plan"]
    # The plan writer actually ran: its node-named message is in the parked state.
    message_names = [getattr(m, "name", None) for m in parked_at_plan["messages"]]
    assert "plan_author" in message_names
    # The gate three park is durable state on the run's own thread.
    assert parked_at_plan["gate_phase"] == "plan"
    assert parked_at_plan["thread_id"] == run_thread_id


@pytest.mark.asyncio
async def test_plan_gate_request_changes_loops_the_plan_writer(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """A ``request_changes`` verdict at gate three revises the plan, not the ADR.

    The third gate must route its revision back to the PLAN writer: a gate that
    fell back to the ADR writer would silently re-open a decision the human already
    accepted. Proven over the real graph by resuming gate three with
    ``request_changes`` and asserting the run re-parks on the plan gate with a
    second plan submission and a second plan-author pass.
    """
    submitter = _FakeSubmitter()
    team = _research_adr_team([ResearchThreadSpec(thread_id="codebase")])
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
        model_assignment=deterministic_model_assignment(team),
    )

    run_thread_id = "ra-plan-revision-run"
    config: RunnableConfig = {"configurable": {"thread_id": run_thread_id}}
    state: dict[str, Any] = {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research and plan the phase machine.")],
        "next": "",
        "thread_id": run_thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }

    approve = Command[str](resume={"verdict": "approved", "notes": None})
    await graph.ainvoke(state, config=config)
    await graph.ainvoke(approve, config=config)
    await graph.ainvoke(approve, config=config)
    assert submitter.phases == ["research", "adr", "plan"]

    revise = Command[str](
        resume={"verdict": "request_changes", "notes": "Step S02 has no success check."}
    )
    reparked = await graph.ainvoke(revise, config=config)

    assert reparked["__interrupt__"][0].value["phase"] == "plan"
    # The revision looped the PLAN writer, not the ADR writer: exactly one more
    # plan submission, and no fourth ADR one.
    assert submitter.phases == ["research", "adr", "plan", "plan"]
    plan_passes = [
        m for m in reparked["messages"] if getattr(m, "name", None) == "plan_author"
    ]
    assert len(plan_passes) == 2
    # The reviewer's note reached the writer as a concrete revise signal.
    assert "Step S02 has no success check." in reparked["validation_errors"]
