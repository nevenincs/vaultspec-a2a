"""Live receipt proof: a document-persona graph agent receives its role-scoped
rule conventions AT THE AGENT BOUNDARY in the REAL compiled graph (P05.S11).

The graph-agent-framework-harness ADR is explicit that a static-repo
``RuleManager.compile()`` returning non-None is INSUFFICIENT proof: the scoped
conventions must actually reach the model an executing document node hands its
messages to, in a graph produced by the real ``compile_team_graph`` wiring
(P04.S09/S10 threads ``role=agent_cfg.role`` into ``create_worker_node``; the
worker gates the bundled conventions on document roles). These tests exercise
that wiring end to end without the engine.

The model boundary is instrumented, not the system under test: a recording
``BaseChatModel`` is returned through the REAL provider-selection seam (the
``provider_factory`` parameter ``compile_team_graph`` already accepts and calls
per worker), never monkeypatched onto a compiled node. Everything under test is
real - the real ``compile_team_graph``, the real ``RuleManager``, the real
worker node, and the real bundled conventions shipped under
``context/presets/rules/``. An engine is never contacted, so these run under
``-m service`` on any host (the workspace is a bare on-disk tmp dir, the Path B
bundled-only default the ADR names).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from ..graph.compiler import compile_team_graph
from ..team import load_agent_config, load_team_config
from ..thread.errors import AgentConfigNotFoundError

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.graph.state import CompiledStateGraph

    from ..thread.state import TeamState

# The bundled document-authoring conventions carry this heading; the worker wraps
# a compiled rule string in its own "Project Coding Rules & Guidelines" system
# message. Asserting the taxonomy heading proves the BUNDLED conventions (not just
# any rule text) reached the boundary.
_CONVENTIONS_MARKER = "Tag taxonomy"
_WORKER_RULES_HEADER = "Project Coding Rules & Guidelines"

# A unique marker planted in a workspace-local rule file, used to prove the
# role=None coder path still compiles the whole workspace corpus (coder rules are
# never stripped) while the document conventions stay scoped out.
_WORKSPACE_CODER_MARKER = "WORKSPACE_CODER_MARKER_run-linter"

_RESEARCH_ADR_PRESET = "vaultspec-adr-research-deterministic"
_CODER_PRESET = "vaultspec-solo-coder"


class _RecordingChatModel(BaseChatModel):
    """A real ``BaseChatModel`` that records every message list it is handed.

    Not a mock of the system under test - it stands in for the external LLM
    provider (never callable in CI) exactly at the boundary being asserted: the
    messages the executing node hands the model. Returns a benign completion so
    the node finishes its turn.
    """

    _calls: list[list[BaseMessage]]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, "_calls", [])

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
        raise NotImplementedError("recording model is async-only")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._calls.append(list(messages))
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="acknowledged"))]
        )


class _RecordingProviderFactory:
    """A ``ProviderFactoryProtocol`` that yields a recording model per worker.

    Ignores the requested provider (the point is to intercept at the real
    selection seam, not to exercise a network provider) and keys each created
    model by the worker's short role so a test can read back exactly what a given
    persona's node received.
    """

    def __init__(self) -> None:
        self.by_role: dict[str, _RecordingChatModel] = {}

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> _RecordingChatModel:
        recorder = _RecordingChatModel()
        key = (
            getattr(agent_config, "role", None)
            or getattr(agent_config, "id", None)
            or "supervisor"
        )
        self.by_role[str(key)] = recorder
        return recorder


class _StubProposalSubmitter:
    """Idempotent no-network submitter; only invoked at gate nodes, not writers."""

    async def __call__(self, state: TeamState, phase: str) -> str:
        return f"proposal:{phase}"


def _document_state(feature: str, workspace_root: Path) -> TeamState:
    return {
        "active_agent": "adr-author",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Author the document.")],
        "next": "",
        "thread_id": "receipt-proof",
        "active_feature": feature,
        "workspace_root": str(workspace_root),
        "token_usage": {},
    }


def _system_texts(calls: list[list[BaseMessage]]) -> list[str]:
    """Every SystemMessage content string across all recorded calls."""
    return [
        msg.content
        for call in calls
        for msg in call
        if isinstance(msg, SystemMessage) and isinstance(msg.content, str)
    ]


def _compile_research_adr(
    workspace_root: Path, factory: _RecordingProviderFactory
) -> CompiledStateGraph:
    team = load_team_config(_RESEARCH_ADR_PRESET)
    assert team.topology.type == "research_adr"
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    return compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=InMemorySaver(),
        workspace_root=workspace_root,
        provider_factory=factory,
        proposal_submitter=_StubProposalSubmitter(),
        feature_tag="receipt-proof",
    )


@pytest.mark.asyncio
async def test_document_node_receives_bundled_conventions_over_bare_workspace(
    tmp_path: Path,
) -> None:
    """A compiled research_adr document node is handed the bundled conventions.

    Path B (bundled-only): the workspace has NO ``.vaultspec/rules`` yet the
    document node's model still receives the taxonomy conventions - proving the
    receipt at the agent boundary, not a static ``compile()`` call, and that a
    bare workspace is not refused by the compile path (tripwire).
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Path B precondition: genuinely bundled-only, no workspace rule corpus.
    assert not (workspace / ".vaultspec" / "rules").exists()

    factory = _RecordingProviderFactory()
    graph = _compile_research_adr(workspace, factory)

    # The bare bundled-only workspace was NOT refused: the document writer nodes
    # are present in the compiled graph.
    node_names = {name for name in graph.nodes if not name.startswith("__")}
    assert {"adr_author", "synthesis"} <= node_names

    # Invoke two document writer nodes (both created via the compiler's
    # role-threaded create_worker_node) and inspect what their model received.
    for writer in ("adr_author", "synthesis"):
        await graph.nodes[writer].ainvoke(
            _document_state("receipt-proof", workspace),
            {"configurable": {"thread_id": f"receipt-{writer}"}},
        )

    for role in ("adr-author", "synthesist"):
        recorder = factory.by_role.get(role)
        assert recorder is not None, f"no model was created for the {role!r} persona"
        assert recorder.calls, f"the {role!r} document node never called its model"
        system_texts = _system_texts(recorder.calls)
        assert any(_CONVENTIONS_MARKER in text for text in system_texts), (
            f"the {role!r} document node's system messages did not carry the "
            f"bundled {_CONVENTIONS_MARKER!r} conventions: {system_texts}"
        )
        assert any(_WORKER_RULES_HEADER in text for text in system_texts), (
            f"the {role!r} conventions were not delivered under the worker rules "
            f"header: {system_texts}"
        )


@pytest.mark.asyncio
async def test_live_research_adr_run_delivers_conventions_to_document_agents(
    tmp_path: Path,
) -> None:
    """Driving the real compiled graph delivers conventions to executing agents.

    The strongest form of the receipt: rather than invoking a node in isolation,
    drive ``ainvoke`` on the compiled research_adr graph over a bare workspace
    until it parks at its first gate. Every document persona that actually
    executed on the way there (researcher, synthesist, doc-reviewer) must have
    been handed the bundled conventions at its model boundary.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    factory = _RecordingProviderFactory()
    graph = _compile_research_adr(workspace, factory)

    # Drive the run; it parks at the first (research) gate via interrupt(). A
    # recursion cap guards against an unexpected revision loop - the document
    # nodes still executed and recorded either way.
    with contextlib.suppress(GraphRecursionError):
        await graph.ainvoke(
            _document_state("receipt-proof", workspace),
            {"configurable": {"thread_id": "receipt-live"}, "recursion_limit": 25},
        )

    executed_document_roles = [
        role
        for role in ("researcher", "synthesist", "doc-reviewer")
        if factory.by_role.get(role) and factory.by_role[role].calls
    ]
    assert executed_document_roles, (
        "no document persona executed while driving the compiled research_adr run"
    )
    for role in executed_document_roles:
        system_texts = _system_texts(factory.by_role[role].calls)
        assert any(_CONVENTIONS_MARKER in text for text in system_texts), (
            f"executing {role!r} agent did not receive the bundled "
            f"{_CONVENTIONS_MARKER!r} conventions in a live run: {system_texts}"
        )


@pytest.mark.asyncio
async def test_coder_role_excluded_from_conventions_but_keeps_workspace_rules(
    tmp_path: Path,
) -> None:
    """A coder-role node is scoped OUT of the document conventions (one-sided-proof
    guard) yet still compiles its whole workspace corpus (role=None regression).

    The negative half is load-bearing: proving document roles GET the conventions
    is only half the contract - a coder must NOT, or the scoping leaks. The
    regression half proves the coder's own workspace rules are never stripped by
    the scoping change (P04): with a workspace rule present, role=None still
    compiles it.
    """
    workspace = tmp_path / "ws"
    rules_dir = workspace / ".vaultspec" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "coder-rules.md").write_text(
        f"# Coder rules\n\n{_WORKSPACE_CODER_MARKER}: always run the linter.\n",
        encoding="utf-8",
    )

    team = load_team_config(_CODER_PRESET)
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    coder_id = team.workers[0].agent_id
    assert agent_configs[coder_id].role == "coder"

    supervisor_cfg = None
    if team.topology.type in ("star", "pipeline_loop"):
        # A missing supervisor config is tolerated (the coder preset may ship
        # none); any other failure is a real regression and must surface.
        with contextlib.suppress(AgentConfigNotFoundError):
            supervisor_cfg = load_agent_config("vaultspec-supervisor")

    factory = _RecordingProviderFactory()
    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=InMemorySaver(),
        workspace_root=workspace,
        supervisor_agent_config=supervisor_cfg,
        provider_factory=factory,
        feature_tag="receipt-proof",
    )

    state: TeamState = {
        "active_agent": coder_id,
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Write code.")],
        "next": "",
        "thread_id": "receipt-coder",
        "workspace_root": str(workspace),
        "token_usage": {},
    }
    await graph.nodes[coder_id].ainvoke(
        state, {"configurable": {"thread_id": "receipt-coder"}}
    )

    recorder = factory.by_role.get("coder")
    assert recorder is not None and recorder.calls, "the coder node never ran"
    system_texts = _system_texts(recorder.calls)

    # Negative: the document conventions are NOT leaked to a coder turn.
    assert not any(_CONVENTIONS_MARKER in text for text in system_texts), (
        f"a coder turn wrongly received the document {_CONVENTIONS_MARKER!r} "
        f"conventions: {system_texts}"
    )
    # Regression: the coder's OWN workspace rule corpus is still compiled (role=None).
    assert any(_WORKSPACE_CODER_MARKER in text for text in system_texts), (
        f"the coder's workspace rule corpus was not compiled (role=None path "
        f"regressed): {system_texts}"
    )
