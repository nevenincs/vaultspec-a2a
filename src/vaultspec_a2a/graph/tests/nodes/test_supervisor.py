"""Tests for deterministic supervisor routing and gating logic."""

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from vaultspec_a2a.thread.state import TeamState

from ...nodes.supervisor import (
    _build_supervisor_messages,
    _evaluate_supervisor_response,
)


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


def test_build_supervisor_messages_adds_workspace_rules() -> None:
    workspace_root = Path(".tmp-supervisor-rules")
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
