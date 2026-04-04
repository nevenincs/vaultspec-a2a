"""Tests for deterministic supervisor routing and gating logic."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command
from pydantic import PrivateAttr

from vaultspec_a2a.thread.state import TeamState

from ...nodes.supervisor import (
    _build_supervisor_messages,
    _evaluate_supervisor_response,
    _phase_for_route,
    _select_revision_worker,
    create_supervisor_node,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


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


def _decision(
    response_text: str,
    *,
    workers: list[str],
    state: TeamState | None = None,
    worker_phase_map: dict[str, str] | None = None,
    autonomous: bool = False,
):
    return _evaluate_supervisor_response(
        state=state or _make_state(),
        response_text=response_text,
        workers=workers,
        worker_phase_map=worker_phase_map,
        autonomous=autonomous,
    )


def _make_state_with_errors(errors: list[str]) -> TeamState:
    state = _make_state()
    state["validation_errors"] = errors
    return state


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


def _make_state_for_phase_gate(
    vault_index: dict,
    active_feature: str | None = "my-feature",
) -> TeamState:
    state = _make_state()
    if active_feature is not None:
        state["active_feature"] = active_feature
    state["vault_index"] = vault_index
    return state


def _make_state_for_plan_approval(
    *,
    active_feature: str | None = "my-feature",
    vault_index: dict[str, list[str]] | None = None,
    approval_status: str | None = None,
) -> TeamState:
    state: TeamState = {
        "messages": [HumanMessage(content="implement the feature")],
        "thread_id": "thread-plan-test",
        "active_agent": "supervisor",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "next": "",
        "vault_index": (
            vault_index
            if vault_index is not None
            else {"plan": [".vault/plan/plan.md"]}
        ),
    }
    if active_feature is not None:
        state["active_feature"] = active_feature
    if approval_status is not None:
        state["approval_status"] = approval_status
    return state


class _StaticSupervisorModel(BaseChatModel):
    """Minimal async chat model that returns a fixed route choice."""

    _content: str = PrivateAttr()

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    @property
    def _llm_type(self) -> str:
        return "static-supervisor-model"

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("_StaticSupervisorModel only supports async")

    async def _agenerate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = AIMessage(content=self._content)
        return ChatResult(generations=[ChatGeneration(message=response)])


def test_supervisor_routing_substring_collision() -> None:
    result = _decision("the coder should handle this", workers=["code", "coder"])
    assert result.next_route == "coder"


def test_supervisor_routing_exact_match_preferred() -> None:
    result = _decision("coder", workers=["code", "coder"])
    assert result.next_route == "coder"


def test_supervisor_routing_finish() -> None:
    result = _decision("FINISH", workers=["planner", "coder"])
    assert result.next_route == "FINISH"


def test_supervisor_routing_unparseable_defaults_to_finish() -> None:
    result = _decision("I have no idea what to do next!", workers=["planner", "coder"])
    assert result.next_route == "FINISH"
    assert result.routing_error is not None


def test_supervisor_sets_routing_error_on_parse_failure() -> None:
    gibberish = "xyzzy forty-two blorp"
    result = _decision(gibberish, workers=["planner", "coder"])
    assert result.next_route == "FINISH"
    assert result.routing_error is not None
    assert gibberish in result.routing_error


def test_supervisor_no_routing_error_on_clean_finish() -> None:
    result = _decision("FINISH", workers=["planner", "coder"])
    assert result.routing_error is None


def test_supervisor_compacts_on_large_state() -> None:
    large_content = "x" * 400_000
    large_state: TeamState = {
        "messages": [HumanMessage(content=large_content)],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test",
        "token_usage": {},
        "next": "",
    }
    messages = _build_supervisor_messages(
        state=large_state, full_prompt="You are a supervisor.", workspace_root=None
    )
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == large_content
    assert len(messages) == 2


def test_supervisor_validation_error_gate_blocks_finish() -> None:
    result = _decision(
        "FINISH",
        workers=["planner", "coder"],
        state=_make_state_with_errors(["missing return type", "unused import"]),
    )
    assert result.next_route == "planner"
    assert result.routing_error is not None
    assert "FINISH blocked" in result.routing_error


def test_supervisor_validation_error_gate_allows_finish_when_no_errors() -> None:
    result = _decision("FINISH", workers=["planner", "coder"], state=_make_state())
    assert result.routing_error is None


def test_review_gate_blocks_finish_when_exec_done_no_audit() -> None:
    result = _decision(
        "FINISH",
        workers=["planner", "reviewer"],
        state=_make_state_with_vault(
            active_feature="my-feature",
            exec_paths=[".vault/exec/my-feature/step-001.md"],
            audit_paths=[],
        ),
    )
    assert result.next_route == "planner"
    assert "FINISH blocked" in result.routing_error


def test_review_gate_allows_finish_when_audit_present() -> None:
    result = _decision(
        "FINISH",
        workers=["planner", "reviewer"],
        state=_make_state_with_vault(
            active_feature="my-feature",
            exec_paths=[".vault/exec/my-feature/step-001.md"],
            audit_paths=[".vault/audit/my-feature-review.md"],
        ),
    )
    assert result.next_route == "FINISH"
    assert result.routing_error is None


def test_phase_gate_hard_blocks_exec_without_plan() -> None:
    result = _decision(
        "coder",
        workers=["coder", "planner"],
        state=_make_state_for_phase_gate(vault_index={}),
        worker_phase_map={"coder": "exec", "planner": "plan"},
    )
    assert result.routing_error is not None
    assert "plan" in result.routing_error


def test_phase_gate_passes_when_prerequisite_satisfied() -> None:
    result = _decision(
        "coder",
        workers=["coder"],
        state=_make_state_for_phase_gate(
            vault_index={"plan": [".vault/plan/my-feature-plan.md"]},
        ),
        worker_phase_map={"coder": "exec"},
        autonomous=True,
    )
    assert result.routing_error is None


def test_plan_approval_interrupt_fires_for_exec_worker() -> None:
    result = _decision(
        "vaultspec-coder",
        workers=["vaultspec-coder"],
        state=_make_state_for_plan_approval(),
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=False,
    )
    assert result.plan_approval_request is not None
    assert result.plan_approval_request["type"] == "plan_approval_request"


def test_plan_approval_interrupt_skipped_in_autonomous_mode() -> None:
    result = _decision(
        "vaultspec-coder",
        workers=["vaultspec-coder"],
        state=_make_state_for_plan_approval(),
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=True,
    )
    assert result.plan_approval_request is None


def test_plan_rejection_prefers_plan_phase_worker_for_revision() -> None:
    worker = _select_revision_worker(
        ["vaultspec-reviewer", "vaultspec-planner", "vaultspec-coder"],
        {
            "vaultspec-reviewer": "audit",
            "vaultspec-planner": "plan",
            "vaultspec-coder": "exec",
        },
    )
    assert worker == "vaultspec-planner"


def test_plan_rejection_falls_back_to_first_worker_without_plan_phase_map() -> None:
    worker = _select_revision_worker(
        ["vaultspec-analyst", "vaultspec-reviewer", "vaultspec-coder"],
        {
            "vaultspec-analyst": "research",
            "vaultspec-reviewer": "audit",
            "vaultspec-coder": "exec",
        },
    )
    assert worker == "vaultspec-analyst"


def test_supervisor_prefers_worker_phase_over_vault_inference() -> None:
    result = _decision(
        "vaultspec-planner",
        workers=["vaultspec-planner", "vaultspec-coder"],
        state=_make_state_for_phase_gate(
            vault_index={
                "plan": [".vault/plan/feature-plan.md"],
                "exec": [".vault/exec/feature/step-001.md"],
            },
            active_feature=None,
        ),
        worker_phase_map={"vaultspec-planner": "plan", "vaultspec-coder": "exec"},
        autonomous=True,
    )
    assert result.next_route == "vaultspec-planner"
    assert result.inferred_phase == "plan"


def test_revision_phase_prefers_revision_worker_phase() -> None:
    phase = _phase_for_route(
        "vaultspec-planner",
        fallback_phase="exec",
        worker_phase_map={"vaultspec-planner": "plan", "vaultspec-coder": "exec"},
    )
    assert phase == "plan"


def test_build_supervisor_messages_adds_workspace_rules(tmp_path: Path) -> None:
    workspace_root = tmp_path / "supervisor-rules"
    rules_dir = workspace_root / ".vaultspec" / "rules" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule_file = rules_dir / "project.md"
    rule_file.write_text("# Repo Rules\n\nDo the thing.\n", encoding="utf-8")
    messages = _build_supervisor_messages(
        state=_make_state(),
        full_prompt="You are a supervisor.",
        workspace_root=workspace_root,
    )
    assert any(
        isinstance(m, SystemMessage) and "Project Coding Rules" in str(m.content)
        for m in messages
    )


@pytest.mark.asyncio
async def test_supervisor_node_clears_stale_routing_error_on_clean_route() -> None:
    """Recovered handoffs must not keep stale approval/routing state."""
    model = _StaticSupervisorModel("vaultspec-coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=True,
    )
    state = _make_state_for_phase_gate(
        vault_index={"plan": [".vault/plan/my-feature-plan.md"]},
    )
    state["approval_status"] = "rejected"
    state["approval_request_id"] = "approval-1"
    state["routing_error"] = "Plan rejected by user — revise before proceeding."

    result = await node(state)

    assert result["next"] == "vaultspec-coder"
    assert result["active_agent"] == "vaultspec-coder"
    assert result["pipeline_phase"] == "exec"
    assert "approval_status" in result
    assert result["approval_status"] is None
    assert "approval_request_id" in result
    assert result["approval_request_id"] is None
    assert "routing_error" in result
    assert result["routing_error"] is None


@pytest.mark.asyncio
async def test_supervisor_parse_failure_clears_stale_approval_state() -> None:
    """Routing failures must not preserve stale approval residue."""
    model = _StaticSupervisorModel("I have no idea what to do next!")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=True,
    )
    state = _make_state_for_phase_gate(
        vault_index={"plan": [".vault/plan/my-feature-plan.md"]},
    )
    state["approval_status"] = "rejected"
    state["approval_request_id"] = "approval-1"
    state["routing_error"] = "Plan rejected by user — revise before proceeding."

    result = await node(state)

    assert result["next"] == "FINISH"
    assert "approval_status" in result
    assert result["approval_status"] is None
    assert "approval_request_id" in result
    assert result["approval_request_id"] is None
    assert "routing_error" in result
    assert result["routing_error"] is not None
    assert "I have no idea" in result["routing_error"]


@pytest.mark.asyncio
async def test_supervisor_resume_clears_stale_routing_error_after_approval() -> None:
    """Approval resume should clear stale rejection context before worker handoff."""
    model = _StaticSupervisorModel("vaultspec-coder")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=False,
    )

    builder = StateGraph(cast("Any", TeamState))
    builder.add_node("supervisor", node)
    builder.set_entry_point("supervisor")
    builder.add_edge("supervisor", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "test-supervisor-resume"}}

    state = _make_state_for_plan_approval(
        vault_index={"plan": [".vault/plan/plan.md"]},
    )
    state["routing_error"] = "Plan rejected by user — revise before proceeding."

    first = await graph.ainvoke(state, config=config)
    assert "__interrupt__" in first

    resumed = await graph.ainvoke(Command(resume={"approved": True}), config=config)
    assert resumed["next"] == "vaultspec-coder"
    assert resumed["approval_status"] == "approved"
    assert "routing_error" in resumed
    assert resumed["routing_error"] is None


@pytest.mark.asyncio
async def test_supervisor_clean_finish_clears_active_agent_owner() -> None:
    """Completed routes should not leave a stale worker marked as active."""
    model = _StaticSupervisorModel("FINISH")
    node = create_supervisor_node(
        model=model,
        system_prompt="You are a supervisor.",
        workers=["vaultspec-coder"],
        worker_phase_map={"vaultspec-coder": "exec"},
        autonomous=True,
    )
    state = _make_state_for_phase_gate(
        vault_index={"plan": [".vault/plan/my-feature-plan.md"]},
        active_feature=None,
    )
    state["active_agent"] = "vaultspec-coder"

    result = await node(state)

    assert result["next"] == "FINISH"
    assert result["active_agent"] == ""
