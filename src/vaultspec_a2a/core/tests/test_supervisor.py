"""Tests for the supervisor node routing logic."""

from typing import Any

import pytest
import pytest_asyncio

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.constants import END, START, TAG_NOSTREAM
from langgraph.graph import StateGraph

from ..nodes.supervisor import create_supervisor_node
from ..state import TeamState


class _StubChatModel(BaseChatModel):
    """Minimal real BaseChatModel subclass that returns a fixed response.

    Uses the real LangChain base class — no mocking involved.
    """

    response_text: str
    # Captures tags from the last invocation config for TAG_NOSTREAM assertions
    captured_tags: list[str] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Capture tags from run_manager config if available
        if run_manager is not None:
            tags = getattr(run_manager, "tags", [])
            # Store on class so tests can inspect without instance reference
            _StubChatModel.captured_tags = list(tags)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response_text))]
        )

    @property
    def _llm_type(self) -> str:
        return "stub"


def _make_state() -> TeamState:
    return {
        "messages": [HumanMessage(content="do something")],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test",
        "token_usage": {},
        "next": "",
    }


# ---------------------------------------------------------------------------
# T02 — substring routing collision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_routing_substring_collision() -> None:
    """Longer option wins when one worker name is a substring of another.

    T02: with workers ["code", "coder"], a supervisor response containing
    "the coder should handle this" must route to "coder" (longer match),
    not "code" (which is a substring of "coder").
    """
    model = _StubChatModel(response_text="the coder should handle this")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["code", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "coder", (
        f"Expected 'coder' but got {result['next']!r} — "
        "substring collision: 'code' must not shadow 'coder'"
    )


@pytest.mark.asyncio
async def test_supervisor_routing_exact_match_preferred() -> None:
    """Exact match always wins over substring scan."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["code", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "coder"


@pytest.mark.asyncio
async def test_supervisor_routing_finish() -> None:
    """FINISH exact match routes to FINISH."""
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "FINISH"


@pytest.mark.asyncio
async def test_supervisor_routing_unparseable_defaults_to_finish() -> None:
    """Unparseable response defaults to FINISH."""
    model = _StubChatModel(response_text="I have no idea what to do next!")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "FINISH"
    assert "routing_error" in result
    assert "supervisor could not parse route from" in result["routing_error"]


# ---------------------------------------------------------------------------
# T03 — routing_error field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_sets_routing_error_on_parse_failure() -> None:
    """routing_error is set in state when supervisor response is unparseable.

    T03: on FINISH fallback caused by parse failure (not an intentional FINISH),
    the supervisor must return routing_error containing the raw response text.
    """
    gibberish = "xyzzy forty-two blorp"
    model = _StubChatModel(response_text=gibberish)
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())

    assert result["next"] == "FINISH"
    assert "routing_error" in result, (
        "routing_error key must be present on parse failure"
    )
    assert gibberish in result["routing_error"], (
        f"routing_error should contain the raw response; got: {result['routing_error']!r}"
    )


@pytest.mark.asyncio
async def test_supervisor_no_routing_error_on_clean_finish() -> None:
    """routing_error must NOT be set when the supervisor intentionally responds FINISH."""
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())

    assert result["next"] == "FINISH"
    assert "routing_error" not in result, (
        "routing_error must not be set when FINISH is an exact match"
    )


# ---------------------------------------------------------------------------
# T06 — context compaction in supervisor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_compacts_on_large_state() -> None:
    """Supervisor compacts messages when state exceeds 80% of CONTEXT_LIMIT.

    T06: When the conversation history is large, compact_context is applied
    before building the messages list. After compaction the supervisor still
    routes correctly (compaction is transparent to routing).
    """
    # Build a state whose messages exceed the 80% threshold.
    # CONTEXT_LIMIT = 120_000 tokens; threshold = 96_000 tokens.
    # estimate_tokens uses 4 chars/token, so we need > 96_000 * 4 = 384_000 chars.
    large_content = "x" * 400_000  # ~100_000 tokens — above threshold
    large_state: TeamState = {
        "messages": [HumanMessage(content=large_content)],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test",
        "token_usage": {},
        "next": "",
    }

    model = _StubChatModel(response_text="planner")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    # Must not raise and must route correctly despite large state
    result = await node(large_state)
    assert result["next"] == "planner"


# ---------------------------------------------------------------------------
# T07 — TAG_NOSTREAM applied to supervisor routing invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_routing_uses_tag_nostream() -> None:
    """Supervisor invokes the routing model with TAG_NOSTREAM to suppress streaming.

    T07: model.with_config({"tags": [TAG_NOSTREAM]}) is called before ainvoke,
    so the routing tokens do not appear in on_chat_model_stream events emitted
    to the UI. We verify TAG_NOSTREAM is present in the run_manager tags
    captured during _generate.
    """
    _StubChatModel.captured_tags = []  # reset before test
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    result = await node(_make_state())
    assert result["next"] == "coder"

    # TAG_NOSTREAM must have been present in the config tags during ainvoke
    assert TAG_NOSTREAM in _StubChatModel.captured_tags, (
        f"Expected TAG_NOSTREAM ({TAG_NOSTREAM!r}) in captured tags, "
        f"got: {_StubChatModel.captured_tags!r}"
    )


# ---------------------------------------------------------------------------
# ADR-022 — validation error gate blocks FINISH
# ---------------------------------------------------------------------------


def _make_state_with_errors(errors: list[str]) -> TeamState:
    state = _make_state()
    state["validation_errors"] = errors
    return state


@pytest.mark.asyncio
async def test_supervisor_validation_error_gate_blocks_finish() -> None:
    """When validation_errors are present, FINISH is blocked and rerouted to workers[0].

    ADR-022: supervisor must not allow FINISH while validation errors remain.
    """
    model = _StubChatModel(response_text="FINISH")
    workers = ["planner", "coder"]
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=workers,
    )

    state = _make_state_with_errors(["missing return type", "unused import"])
    result = await node(state)

    assert result["next"] == "planner", (
        f"Expected reroute to first worker 'planner', got {result['next']!r}"
    )
    assert "routing_error" in result
    assert "FINISH blocked" in result["routing_error"]
    assert "2 validation error(s)" in result["routing_error"]


@pytest.mark.asyncio
async def test_supervisor_validation_error_gate_allows_finish_when_no_errors() -> None:
    """FINISH proceeds normally when validation_errors is empty or absent."""
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    # No validation_errors key at all
    result = await node(_make_state())
    assert result["next"] == "FINISH"
    assert "routing_error" not in result

    # Empty validation_errors list
    state = _make_state_with_errors([])
    result = await node(state)
    assert result["next"] == "FINISH"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_supervisor_validation_error_gate_does_not_block_worker_route() -> None:
    """Routing to a worker (not FINISH) is unaffected by validation errors."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "coder"],
    )

    state = _make_state_with_errors(["some error"])
    result = await node(state)
    assert result["next"] == "coder"
    assert "routing_error" not in result


# ---------------------------------------------------------------------------
# ADR-025 — mandatory review gate blocks FINISH
# ---------------------------------------------------------------------------


def _make_state_with_vault(
    active_feature: str | None,
    exec_paths: list[str],
    audit_paths: list[str],
) -> TeamState:
    state = _make_state()
    if active_feature is not None:
        state["active_feature"] = active_feature
    vault_index: dict[str, list[str]] = {}
    if exec_paths:
        vault_index["exec"] = exec_paths
    if audit_paths:
        vault_index["audit"] = audit_paths
    state["vault_index"] = vault_index
    return state


@pytest.mark.asyncio
async def test_review_gate_blocks_finish_when_exec_done_no_audit() -> None:
    """FINISH blocked when active_feature set + exec non-empty + audit empty.

    ADR-025: the mandatory review gate must reroute to workers[0] with a
    routing_error message that states a review artifact is required.
    """
    model = _StubChatModel(response_text="FINISH")
    workers = ["planner", "reviewer"]
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=workers,
    )

    state = _make_state_with_vault(
        active_feature="my-feature",
        exec_paths=[".vault/exec/my-feature/step-001.md"],
        audit_paths=[],
    )
    result = await node(state)

    assert result["next"] == "planner"
    assert "routing_error" in result
    assert "FINISH blocked" in result["routing_error"]
    assert "audit" in result["routing_error"]


@pytest.mark.asyncio
async def test_review_gate_allows_finish_when_audit_present() -> None:
    """FINISH allowed when vault_index['audit'] is non-empty.

    ADR-025: gate passes once any review artifact exists.
    """
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "reviewer"],
    )

    state = _make_state_with_vault(
        active_feature="my-feature",
        exec_paths=[".vault/exec/my-feature/step-001.md"],
        audit_paths=[".vault/audit/my-feature-review.md"],
    )
    result = await node(state)

    assert result["next"] == "FINISH"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_review_gate_skipped_when_no_active_feature() -> None:
    """Gate skipped when active_feature is None — non-SDD thread.

    ADR-025 §2.5: gate is irrelevant without a feature.
    """
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "reviewer"],
    )

    state = _make_state_with_vault(
        active_feature=None,
        exec_paths=[".vault/exec/something.md"],
        audit_paths=[],
    )
    result = await node(state)

    assert result["next"] == "FINISH"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_review_gate_skipped_when_no_exec_work() -> None:
    """Gate skipped when vault_index['exec'] is empty — no execution work done.

    ADR-025: gate fires only when exec work has been done.
    """
    model = _StubChatModel(response_text="FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "reviewer"],
    )

    state = _make_state_with_vault(
        active_feature="my-feature",
        exec_paths=[],
        audit_paths=[],
    )
    result = await node(state)

    assert result["next"] == "FINISH"
    assert "routing_error" not in result


# ---------------------------------------------------------------------------
# ADR-023 — phase artifact prerequisite gates
# ---------------------------------------------------------------------------


def _make_state_for_phase_gate(
    vault_index: dict,
    active_feature: str | None = "my-feature",
) -> "TeamState":
    state = _make_state()
    if active_feature is not None:
        state["active_feature"] = active_feature
    state["vault_index"] = vault_index
    return state


@pytest.mark.asyncio
async def test_phase_gate_hard_blocks_exec_without_plan() -> None:
    """HARD gate blocks exec routing when vault_index['plan'] is empty."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["coder", "planner"],
        worker_phase_map={"coder": "exec", "planner": "plan"},
    )
    state = _make_state_for_phase_gate(vault_index={})
    result = await node(state)

    assert result["next"] == "coder"  # next_route preserved (supervisor intent)
    assert "routing_error" in result
    assert "exec" in result["routing_error"]
    assert "plan" in result["routing_error"]


@pytest.mark.asyncio
async def test_phase_gate_hard_blocks_plan_without_adr() -> None:
    """HARD gate blocks plan routing when vault_index['adr'] is empty."""
    model = _StubChatModel(response_text="planner")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["planner", "analyst"],
        worker_phase_map={"planner": "plan", "analyst": "adr"},
    )
    state = _make_state_for_phase_gate(vault_index={})
    result = await node(state)

    assert result["next"] == "planner"
    assert "routing_error" in result
    assert "plan" in result["routing_error"]
    assert "adr" in result["routing_error"]


@pytest.mark.asyncio
async def test_phase_gate_hard_blocks_audit_without_exec() -> None:
    """HARD gate blocks audit routing when vault_index['exec'] is empty."""
    model = _StubChatModel(response_text="reviewer")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["reviewer", "coder"],
        worker_phase_map={"reviewer": "audit", "coder": "exec"},
    )
    state = _make_state_for_phase_gate(vault_index={})
    result = await node(state)

    assert result["next"] == "reviewer"
    assert "routing_error" in result
    assert "audit" in result["routing_error"]
    assert "exec" in result["routing_error"]


@pytest.mark.asyncio
async def test_phase_gate_soft_warns_adr_without_research() -> None:
    """SOFT gate warns but allows adr routing when vault_index['research'] is empty."""
    model = _StubChatModel(response_text="analyst")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["analyst", "researcher"],
        worker_phase_map={"analyst": "adr", "researcher": "research"},
    )
    state = _make_state_for_phase_gate(vault_index={})
    result = await node(state)

    assert result["next"] == "analyst"  # soft gate: routing proceeds
    assert "routing_error" in result
    assert "adr" in result["routing_error"]
    assert "research" in result["routing_error"]


@pytest.mark.asyncio
async def test_phase_gate_passes_when_prerequisite_satisfied() -> None:
    """Gate passes when required vault_index entry is non-empty."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["coder"],
        worker_phase_map={"coder": "exec"},
        autonomous=True,  # skip ADR-024 interrupt — testing ADR-023 gate only
    )
    state = _make_state_for_phase_gate(
        vault_index={"plan": [".vault/plan/my-feature-plan.md"]},
    )
    result = await node(state)

    assert result["next"] == "coder"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_phase_gate_skipped_when_no_active_feature() -> None:
    """Gates skipped when active_feature is None — non-SDD thread."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["coder"],
        worker_phase_map={"coder": "exec"},
    )
    state = _make_state_for_phase_gate(vault_index={}, active_feature=None)
    result = await node(state)

    assert result["next"] == "coder"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_phase_gate_skipped_when_worker_unmapped() -> None:
    """Gate skipped for workers not in worker_phase_map (conservative default)."""
    model = _StubChatModel(response_text="generalist")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["generalist"],
        worker_phase_map={"coder": "exec"},  # generalist not mapped
    )
    state = _make_state_for_phase_gate(vault_index={})
    result = await node(state)

    assert result["next"] == "generalist"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_phase_gate_skipped_when_no_worker_phase_map() -> None:
    """Gates skipped entirely when worker_phase_map is None (default)."""
    model = _StubChatModel(response_text="coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["coder"],
        # worker_phase_map omitted — defaults to None
    )
    state = _make_state_for_phase_gate(vault_index={})
    result = await node(state)

    assert result["next"] == "coder"


# ---------------------------------------------------------------------------
# ADR-024: Plan approval interrupt tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def checkpointer(tmp_path):
    """Provide a real AsyncSqliteSaver backed by a per-test file (MOCK-06)."""
    db_file = tmp_path / "test_checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(db_file)) as cp:
        await cp.setup()
        yield cp


def _make_state_for_plan_approval(
    *,
    active_feature: str | None = "my-feature",
    vault_index: dict[str, list[str]] | None = None,
    plan_approved: bool | None = None,
) -> TeamState:
    """Build a state fixture for plan approval gate tests."""
    state: dict[str, Any] = {
        "messages": [HumanMessage(content="implement the feature")],
        "thread_id": "thread-plan-test",
        "active_agent": "supervisor",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "vault_index": vault_index
        if vault_index is not None
        else {"plan": [".vault/plan/plan.md"]},
    }
    if active_feature is not None:
        state["active_feature"] = active_feature
    if plan_approved is not None:
        state["plan_approved"] = plan_approved
    return state  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_plan_approval_interrupt_fires_for_exec_worker(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Plan approval interrupt raises GraphInterrupt when routing to exec worker.

    ADR-024 §2.2: fires when all conditions hold — routing to exec worker,
    plan artifact present, active_feature set, plan_approved not True.

    Uses a real compiled StateGraph so interrupt() has the required
    LangGraph runnable context.
    """
    model = _StubChatModel(response_text="vaultspec-coder")
    supervisor = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=False,
    )

    async def _noop_worker(state: TeamState) -> dict:
        return {}

    builder: StateGraph = StateGraph(TeamState)  # type: ignore[type-var]
    builder.add_node("supervisor", supervisor)
    builder.add_node("vaultspec-coder", _noop_worker)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda s: s.get("next", "FINISH"),
        {"vaultspec-coder": "vaultspec-coder", "FINISH": END},
    )
    builder.add_edge("vaultspec-coder", END)
    graph = builder.compile(checkpointer=checkpointer)

    state = _make_state_for_plan_approval()
    config: RunnableConfig = {
        "configurable": {"thread_id": "test-plan-approval-interrupt"}
    }

    result = await graph.ainvoke(state, config)

    # LangGraph surfaces interrupts via __interrupt__ key in ainvoke result
    assert "__interrupt__" in result, "Expected interrupt to be set in result"
    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["type"] == "plan_approval_request"
    assert payload["feature"] == "my-feature"
    assert payload["exec_worker"] == "vaultspec-coder"
    assert ".vault/plan/plan.md" in payload["plan_paths"]


@pytest.mark.asyncio
async def test_plan_approval_interrupt_skipped_in_autonomous_mode() -> None:
    """Plan approval interrupt skipped when autonomous=True.

    ADR-024 §2.5: autonomous mode bypasses human-in-the-loop gates.
    """
    model = _StubChatModel(response_text="vaultspec-coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=True,
    )
    state = _make_state_for_plan_approval()

    result = await node(state)
    assert result["next"] == "vaultspec-coder"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_plan_approval_interrupt_skipped_when_no_active_feature() -> None:
    """Plan approval interrupt skipped when active_feature is None.

    ADR-024 §2.6: gate does not apply to non-SDD threads.
    """
    model = _StubChatModel(response_text="vaultspec-coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=False,
    )
    state = _make_state_for_plan_approval(active_feature=None)

    result = await node(state)
    assert result["next"] == "vaultspec-coder"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_plan_approval_interrupt_not_retriggered_when_already_approved() -> None:
    """Plan approval interrupt skipped when plan_approved is already True.

    ADR-024 §2.9: per-session one-time semantics — once approved, subsequent
    exec routing decisions proceed without re-triggering the interrupt.
    """
    model = _StubChatModel(response_text="vaultspec-coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=False,
    )
    state = _make_state_for_plan_approval(plan_approved=True)

    result = await node(state)
    assert result["next"] == "vaultspec-coder"
    assert "routing_error" not in result


@pytest.mark.asyncio
async def test_plan_approval_interrupt_skipped_when_no_plan_artifact() -> None:
    """Plan approval interrupt skipped when vault_index has no plan entries.

    When plan is absent, ADR-023 hard gate fires first (routing_error) before
    reaching the ADR-024 interrupt check.
    """
    model = _StubChatModel(response_text="vaultspec-coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=False,
    )
    # No plan entry — ADR-023 blocks before ADR-024 fires
    state = _make_state_for_plan_approval(vault_index={})

    result = await node(state)
    assert "routing_error" in result


@pytest.mark.asyncio
async def test_plan_approval_interrupt_skipped_when_no_worker_phase_map() -> None:
    """Plan approval interrupt skipped when worker_phase_map is None.

    Without a phase map there is no way to identify exec workers.
    """
    model = _StubChatModel(response_text="vaultspec-coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        # worker_phase_map omitted
        autonomous=False,
    )
    state = _make_state_for_plan_approval()

    result = await node(state)
    assert result["next"] == "vaultspec-coder"
    assert "routing_error" not in result
