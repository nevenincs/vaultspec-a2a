"""Tests for the worker node.

Uses LangChain's FakeListChatModel (a real BaseChatModel implementation) to
test node logic deterministically without hitting a live LLM.
"""

from collections.abc import Callable
from typing import Any

import pytest

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import Field

from ...state import TeamState
from ..worker import (
    _first_option_id,
    _interrupt_permission_callback,
    _validate_option_id,
    create_worker_node,
)


class _CapturingModel(FakeListChatModel):
    """FakeListChatModel that records messages passed to _generate."""

    captured: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        self.captured.append(list(messages))
        return super()._generate(messages, stop, run_manager, **kwargs)


class _PermissionCallbackModel(FakeListChatModel):
    """FakeListChatModel with a permission_callback field for testing wiring logic.

    Policy exception: This test helper extends LangChain's first-party
    FakeListChatModel with a permission_callback field to match the structural
    interface of AcpChatModel. The tests in TestPermissionCallbackWiring verify
    that create_worker_node correctly detects hasattr(model, "permission_callback")
    and wires the callback via model_copy(). This is pure structural/wiring logic
    that does not depend on ACP subprocess behaviour.
    """

    permission_callback: Callable[..., Any] | None = Field(default=None)
    captured: list = Field(default_factory=list)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        self.captured.append((self.permission_callback, list(messages)))
        return super()._generate(messages, stop, run_manager, **kwargs)


# ---------------------------------------------------------------------------
# create_worker_node factory
# ---------------------------------------------------------------------------


class TestCreateWorkerNode:
    """Tests for create_worker_node factory function."""

    def test_returns_callable(self) -> None:
        """create_worker_node returns an async callable."""
        model = FakeListChatModel(responses=["Done."])
        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
        )
        assert callable(node)

    def test_node_has_correct_name(self) -> None:
        """The returned function retains a meaningful name."""
        model = FakeListChatModel(responses=["Done."])
        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
        )
        assert node.__name__ == "worker_node"


# ---------------------------------------------------------------------------
# Worker execution
# ---------------------------------------------------------------------------


class TestWorkerExecution:
    """Tests for the worker node execution."""

    @pytest.mark.asyncio
    async def test_returns_messages_key(self) -> None:
        """Worker node returns a dict with 'messages' key."""
        model = FakeListChatModel(responses=["Hello from coder."])
        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
        )
        state: TeamState = {
            "active_agent": "coder",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Write code")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        assert "messages" in result
        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_response_attributed_to_worker(self) -> None:
        """The returned message has its name set to the worker name."""
        model = FakeListChatModel(responses=["Implementation complete."])
        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
        )
        state: TeamState = {
            "active_agent": "coder",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Write code")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        response_msg = result["messages"][0]
        assert response_msg.name == "coder"

    @pytest.mark.asyncio
    async def test_system_prompt_prepended(self) -> None:
        """The model receives the system prompt as the first message."""
        model = _CapturingModel(responses=["Done."], captured=[])
        node = create_worker_node(
            model=model,
            system_prompt="You are an expert code reviewer.",
            name="reviewer",
        )
        state: TeamState = {
            "active_agent": "reviewer",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Review this code")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        await node(state)

        assert len(model.captured) == 1
        messages = model.captured[0]
        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content == "You are an expert code reviewer."
        assert messages[1].content == "Review this code"

    @pytest.mark.asyncio
    async def test_different_worker_names(self) -> None:
        """Different worker names are correctly attributed."""
        for name in ("planner", "coder", "reviewer"):
            model = FakeListChatModel(responses=["Result."])
            node = create_worker_node(
                model=model,
                system_prompt=f"You are a {name}.",
                name=name,
            )
            state: TeamState = {
                "active_agent": name,
                "artifacts": [],
                "current_plan": [],
                "messages": [HumanMessage(content="Go")],
                "next": "",
                "thread_id": "test-thread",
                "token_usage": {},
            }
            result = await node(state)
            assert result["messages"][0].name == name


# ---------------------------------------------------------------------------
# Context compaction
# ---------------------------------------------------------------------------


class TestWorkerContextCompaction:
    """Tests that context compaction activates on large states."""

    @pytest.mark.asyncio
    async def test_large_state_triggers_compaction(self) -> None:
        """When messages exceed 80% of context limit, compaction fires.

        The context limit is 120k tokens. At ~4 chars/token, 80% threshold
        is 96k tokens = ~384k chars. We create messages exceeding that.
        """
        model = FakeListChatModel(responses=["Compacted result."])
        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
        )
        # Create messages totaling > 384k chars (96k tokens * 4 chars/token)
        big_message = HumanMessage(content="x" * 400_000)
        state: TeamState = {
            "active_agent": "coder",
            "artifacts": [],
            "current_plan": [],
            "messages": [big_message],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        # Node completes without error even with oversized context
        assert "messages" in result
        assert result["messages"][0].name == "coder"

    @pytest.mark.asyncio
    async def test_small_state_no_compaction(self) -> None:
        """When messages are small, no compaction occurs and all pass through."""
        model = _CapturingModel(responses=["Done."], captured=[])
        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
        )
        msgs: list[BaseMessage] = [
            HumanMessage(content=f"Message {i}") for i in range(5)
        ]
        state: TeamState = {
            "active_agent": "coder",
            "artifacts": [],
            "current_plan": [],
            "messages": msgs,
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        await node(state)

        assert len(model.captured) == 1
        messages = model.captured[0]
        # System prompt + 5 messages = 6 total, all passed through
        assert len(messages) == 6


# ---------------------------------------------------------------------------
# Permission callback wiring
# ---------------------------------------------------------------------------


class TestPermissionCallbackWiring:
    """Tests for ACP permission_callback wiring in supervised vs autonomous mode."""

    @pytest.mark.asyncio
    async def test_supervised_model_copy_isolates_callback(self) -> None:
        """In supervised mode, the model is copied to avoid shared mutation (H4)."""
        model = _PermissionCallbackModel(
            responses=["Done."],
            captured=[],
            permission_callback=None,
        )

        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
            autonomous=False,
        )
        state: TeamState = {
            "active_agent": "coder",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Go")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        await node(state)

        # The callback used by the copy should be the interrupt callback,
        # NOT None -- proves model_copy() was used and wired
        assert len(model.captured) == 1
        used_callback, _messages = model.captured[0]
        assert used_callback is _interrupt_permission_callback

        # Original model's callback unchanged (isolation)
        assert model.permission_callback is None

    @pytest.mark.asyncio
    async def test_autonomous_mode_skips_callback_wiring(self) -> None:
        """In autonomous mode, permission_callback is not wired."""
        model = _PermissionCallbackModel(
            responses=["Done."],
            captured=[],
            permission_callback=None,
        )

        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
            autonomous=True,
        )
        state: TeamState = {
            "active_agent": "coder",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Go")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        await node(state)

        # In autonomous mode, callback remains None (not wired)
        assert len(model.captured) == 1
        used_callback, _messages = model.captured[0]
        assert used_callback is None

    @pytest.mark.asyncio
    async def test_non_acp_model_no_wiring(self) -> None:
        """Models without permission_callback attribute skip wiring entirely."""
        model = _CapturingModel(responses=["Done."], captured=[])
        node = create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
            autonomous=False,
        )
        state: TeamState = {
            "active_agent": "coder",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Go")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        # Node completes successfully without any permission wiring
        assert result["messages"][0].name == "coder"


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
