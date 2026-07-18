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

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ..protocols import ProviderFactoryProtocol

from langchain_core.language_models.fake_chat_models import FakeChatModel
from langchain_core.messages import AIMessage

from vaultspec_a2a.team.team_config import (
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from vaultspec_a2a.thread.errors import ConfigError

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


class _NoAuthModel(FakeChatModel):
    """A FakeChatModel that reports the factory's ``none_detected`` auth mode.

    Faithful to the production contract: ``ProviderFactory`` stamps
    ``auth_mode="none_detected"`` on the model it returns when no provider token
    is present in the environment (see ``providers/factory.py``). Modelling that
    here lets the compile gate be exercised without an env-token dependency.
    """

    auth_mode: str = "none_detected"


class _NoneDetectedFactory:
    """Provider factory whose resolved models carry ``auth_mode='none_detected'``."""

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        return _NoAuthModel(responses=["stub response"])


@pytest.mark.asyncio
async def test_research_adr_refuses_armed_preset_without_auth(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """An armed preset (declares a harness) whose models resolve to
    ``auth_mode='none_detected'`` is refused at compile: the run could not
    establish the config-home isolation the declared MCP surface requires, so it
    would spawn unisolated and inherit ambient + workspace MCP (the S20 leak).

    Contrast: ``test_research_adr_compiles_expected_node_set`` compiles the SAME
    armed preset with the default stub factory (no ``none_detected``), proving the
    gate refuses only on the missing-auth condition, not on being armed.
    """
    team = _research_adr_team()
    assert team.effective_harness() is not None  # armed: declares harness servers
    factory = _NoneDetectedFactory()
    with pytest.raises(ConfigError, match="none_detected"):
        compile_team_graph(
            team_config=team,
            agent_configs=_agent_configs(team),
            checkpointer=checkpointer,
            provider_factory=factory,
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
