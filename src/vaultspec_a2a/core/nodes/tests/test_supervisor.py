"""Tests for deterministic supervisor node helpers."""

from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from vaultspec_a2a.thread.state import TeamState

from ..supervisor import _build_supervisor_messages, _evaluate_supervisor_response


def _make_state() -> TeamState:
    return {
        "active_agent": "supervisor",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Write some code")],
        "next": "",
        "thread_id": "test-thread",
        "token_usage": {},
    }


def test_exact_match_routes_to_worker() -> None:
    result = _evaluate_supervisor_response(
        state=_make_state(),
        response_text="coder",
        workers=["coder", "reviewer"],
        worker_phase_map=None,
        autonomous=False,
    )
    assert result.next_route == "coder"


def test_substring_fallback_case_insensitive() -> None:
    result = _evaluate_supervisor_response(
        state=_make_state(),
        response_text="I think the CODER should handle this.",
        workers=["coder", "reviewer"],
        worker_phase_map=None,
        autonomous=False,
    )
    assert result.next_route == "coder"


def test_no_match_defaults_to_finish() -> None:
    result = _evaluate_supervisor_response(
        state=_make_state(),
        response_text="I have no idea what to do.",
        workers=["coder", "reviewer"],
        worker_phase_map=None,
        autonomous=False,
    )
    assert result.next_route == "FINISH"
    assert result.routing_error is not None


def test_conversation_messages_passed_after_system() -> None:
    human_msg = HumanMessage(content="Please code something")
    ai_msg = AIMessage(content="Working on it")
    state = _make_state()
    msgs: list[BaseMessage] = [human_msg, ai_msg]
    state["messages"] = msgs

    messages = _build_supervisor_messages(
        state=state,
        full_prompt="You are the supervisor.",
        workspace_root=None,
    )

    assert len(messages) == 3
    assert isinstance(messages[0], SystemMessage)
    assert messages[1] is human_msg
    assert messages[2] is ai_msg


def test_build_supervisor_messages_adds_workspace_rules(
    tmp_path: Path,
) -> None:
    rules_dir = tmp_path / ".vaultspec" / "rules" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "project.md").write_text(
        "# Repo Rules\n\nDo the thing.\n",
        encoding="utf-8",
    )

    messages = _build_supervisor_messages(
        state=_make_state(),
        full_prompt="You are the supervisor.",
        workspace_root=tmp_path,
    )

    assert any(
        isinstance(message, SystemMessage)
        and isinstance(message.content, str)
        and "Project Coding Rules & Guidelines" in message.content
        for message in messages
    )
