"""Tests for deterministic worker node helpers."""

import sys

from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ....providers.acp_chat_model import AcpChatModel
from ...state import TeamState
from ..worker import (
    _build_worker_messages,
    _finalize_worker_response,
    _first_option_id,
    _interrupt_permission_callback,
    _resolve_effective_worker_model,
    _validate_option_id,
)


# ---------------------------------------------------------------------------
# _first_option_id helper
# ---------------------------------------------------------------------------


class TestFirstOptionId:
    """Tests for the _first_option_id helper function."""

    def test_returns_first_option(self) -> None:
        """Returns the optionId of the first option in the list."""
        options = [
            {"optionId": "allow_once", "label": "Allow"},
            {"optionId": "deny", "label": "Deny"},
        ]
        assert _first_option_id(options) == "allow_once"

    def test_empty_options_returns_default(self) -> None:
        """Returns 'allow_once' when options list is empty."""
        assert _first_option_id([]) == "allow_once"


# ---------------------------------------------------------------------------
# _validate_option_id helper
# ---------------------------------------------------------------------------


class TestValidateOptionId:
    """Tests for the _validate_option_id helper function."""

    def test_valid_candidate_returned(self) -> None:
        """A candidate matching a known optionId is returned as-is."""
        options = [
            {"optionId": "allow_once"},
            {"optionId": "deny"},
        ]
        assert _validate_option_id("deny", options) == "deny"

    def test_invalid_candidate_falls_back_to_first(self) -> None:
        """An unknown candidate falls back to the first optionId."""
        options = [
            {"optionId": "allow_once"},
            {"optionId": "deny"},
        ]
        assert _validate_option_id("hack_it", options) == "allow_once"

    def test_empty_options_returns_default(self) -> None:
        """With no options, falls back to 'allow_once'."""
        assert _validate_option_id("anything", []) == "allow_once"

    def test_all_options_valid(self) -> None:
        """When all options have optionId, the first valid match is used."""
        options = [
            {"optionId": "allow_once"},
            {"optionId": "allow_session"},
            {"optionId": "deny"},
        ]
        assert _validate_option_id("allow_session", options) == "allow_session"
        assert _validate_option_id("deny", options) == "deny"
        assert _validate_option_id("unknown", options) == "allow_once"


SIMULATOR_PATH = Path(__file__).parent.parent.parent / "tests" / "acp_simulator.py"
PYTHON_EXE = sys.executable


def _make_state() -> TeamState:
    return {
        "active_agent": "coder",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Write code")],
        "next": "",
        "thread_id": "test-thread",
        "token_usage": {},
    }


def test_build_worker_messages_prepends_system_prompt() -> None:
    messages = _build_worker_messages(
        state=_make_state(),
        system_prompt="You are an expert code reviewer.",
        workspace_root=None,
    )

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "You are an expert code reviewer."
    assert messages[1].content == "Write code"


def test_build_worker_messages_passes_small_context_without_compaction() -> None:
    state = _make_state()
    msgs: list[BaseMessage] = [HumanMessage(content=f"Message {i}") for i in range(5)]
    state["messages"] = msgs

    messages = _build_worker_messages(
        state=state,
        system_prompt="You are a coder.",
        workspace_root=None,
    )

    assert len(messages) == 6
    assert messages[1:] == state["messages"]


def test_build_worker_messages_handles_large_context() -> None:
    state = _make_state()
    msgs: list[BaseMessage] = [HumanMessage(content="x" * 400_000)]
    state["messages"] = msgs

    messages = _build_worker_messages(
        state=state,
        system_prompt="You are a coder.",
        workspace_root=None,
    )

    assert isinstance(messages[0], SystemMessage)
    assert messages[1].content


def test_build_worker_messages_adds_workspace_rules() -> None:
    workspace_root = Path(".tmp-worker-node-rules")
    rules_dir = workspace_root / ".vaultspec" / "rules" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "project.md").write_text(
        "# Repo Rules\n\nDo the thing.\n",
        encoding="utf-8",
    )

    messages = _build_worker_messages(
        state=_make_state(),
        system_prompt="You are a coder.",
        workspace_root=workspace_root,
    )

    assert any(
        isinstance(message, SystemMessage)
        and isinstance(message.content, str)
        and "Project Coding Rules & Guidelines" in message.content
        for message in messages
    )


def test_resolve_effective_worker_model_wires_acp_callback_in_supervised_mode() -> None:
    model = AcpChatModel(
        command=[PYTHON_EXE, str(SIMULATOR_PATH), "--response", "ok"],
        env_vars={},
    )

    effective_model = _resolve_effective_worker_model(model=model, autonomous=False)

    assert effective_model is not model
    assert isinstance(effective_model, AcpChatModel)
    assert effective_model.permission_callback is _interrupt_permission_callback
    assert model.permission_callback is None


def test_resolve_effective_worker_model_skips_callback_in_autonomous_mode() -> None:
    model = AcpChatModel(
        command=[PYTHON_EXE, str(SIMULATOR_PATH), "--response", "ok"],
        env_vars={},
    )

    effective_model = _resolve_effective_worker_model(model=model, autonomous=True)

    assert effective_model is model
    assert model.permission_callback is None


def test_resolve_effective_worker_model_leaves_non_acp_models_untouched() -> None:
    model = ChatOpenAI(model_name="gpt-4o-mini", openai_api_key=SecretStr("test"))

    effective_model = _resolve_effective_worker_model(model=model, autonomous=False)

    assert effective_model is model


def test_finalize_worker_response_attributes_message_to_worker() -> None:
    response = AIMessage(content="Implementation complete.")

    result = _finalize_worker_response(
        response=response,
        worker_name="coder",
        state_updates={"current_task_id": "task-123"},
    )

    assert result["messages"][0].name == "coder"
    assert result["mounted_context"] is None
    assert result["current_task_id"] == "task-123"
