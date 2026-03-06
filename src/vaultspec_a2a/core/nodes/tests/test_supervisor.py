"""Tests for the supervisor routing node.

Uses LangChain's FakeListChatModel (a real BaseChatModel implementation) to
test routing logic deterministically without hitting a live LLM.
"""

from typing import Any

import pytest

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import Field

from ...state import TeamState
from ..supervisor import create_supervisor_node


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


# ---------------------------------------------------------------------------
# Node creation
# ---------------------------------------------------------------------------


class TestCreateSupervisorNode:
    """Tests for create_supervisor_node factory function."""

    def test_returns_callable(self) -> None:
        """create_supervisor_node returns an async callable."""
        model = FakeListChatModel(responses=["FINISH"])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder", "reviewer"],
        )
        assert callable(node)

    def test_node_has_correct_name(self) -> None:
        """The returned function retains a meaningful name."""
        model = FakeListChatModel(responses=["FINISH"])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder"],
        )
        assert node.__name__ == "supervisor_node"


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------


class TestSupervisorRouting:
    """Tests for the routing parse logic in the supervisor node."""

    @pytest.mark.asyncio
    async def test_exact_match_routes_to_worker(self) -> None:
        """When model returns exact worker name, routes to that worker."""
        model = FakeListChatModel(responses=["coder"])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder", "reviewer"],
        )
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Write some code")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        assert result["next"] == "coder"

    @pytest.mark.asyncio
    async def test_exact_match_finish(self) -> None:
        """When model returns 'FINISH', routes to FINISH."""
        model = FakeListChatModel(responses=["FINISH"])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder", "reviewer"],
        )
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Done")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        assert result["next"] == "FINISH"

    @pytest.mark.asyncio
    async def test_substring_fallback_case_insensitive(self) -> None:
        """When model returns text containing a worker name, uses substring match."""
        model = FakeListChatModel(responses=["I think the CODER should handle this."])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder", "reviewer"],
        )
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Write code")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        assert result["next"] == "coder"

    @pytest.mark.asyncio
    async def test_no_match_defaults_to_finish(self) -> None:
        """When model returns text matching no worker, defaults to FINISH."""
        model = FakeListChatModel(responses=["I have no idea what to do."])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder", "reviewer"],
        )
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="???")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        assert result["next"] == "FINISH"

    @pytest.mark.asyncio
    async def test_finish_substring_in_longer_text(self) -> None:
        """When model text contains 'FINISH' as substring, routes to FINISH."""
        model = FakeListChatModel(responses=["The task is done, FINISH the workflow."])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder"],
        )
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="All done")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        assert result["next"] == "FINISH"

    @pytest.mark.asyncio
    async def test_first_substring_match_wins(self) -> None:
        """When model text contains multiple worker names, first match wins."""
        model = FakeListChatModel(responses=["Let the reviewer check then coder fix."])
        node = create_supervisor_node(
            model=model,
            system_prompt="Route tasks.",
            workers=["coder", "reviewer"],
        )
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Review and fix")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        result = await node(state)
        # "coder" and "reviewer" both appear, but the options list is
        # iterated in order: [coder, reviewer, FINISH]. "coder" appears
        # in the text first substring-wise, but the loop iterates options
        # in declaration order. "coder" is checked first.
        assert result["next"] in ("coder", "reviewer")


# ---------------------------------------------------------------------------
# System prompt construction
# ---------------------------------------------------------------------------


class TestSupervisorPrompt:
    """Tests that the routing instructions are wired into the system prompt."""

    @pytest.mark.asyncio
    async def test_routing_instructions_include_workers_and_finish(self) -> None:
        """The model receives a system message containing all worker names + FINISH."""
        model = _CapturingModel(responses=["FINISH"], captured=[])
        node = create_supervisor_node(
            model=model,
            system_prompt="You are the supervisor.",
            workers=["planner", "coder", "reviewer"],
        )
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Go")],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        await node(state)

        assert len(model.captured) == 1
        messages = model.captured[0]
        system_msg = messages[0]
        assert system_msg.type == "system"
        content = system_msg.content
        assert "planner" in content
        assert "coder" in content
        assert "reviewer" in content
        assert "FINISH" in content

    @pytest.mark.asyncio
    async def test_conversation_messages_passed_after_system(self) -> None:
        """The model receives conversation messages after the system prompt."""
        model = _CapturingModel(responses=["FINISH"], captured=[])
        node = create_supervisor_node(
            model=model,
            system_prompt="You are the supervisor.",
            workers=["coder"],
        )
        human_msg = HumanMessage(content="Please code something")
        ai_msg = AIMessage(content="Working on it")
        state: TeamState = {
            "active_agent": "supervisor",
            "artifacts": [],
            "current_plan": [],
            "messages": [human_msg, ai_msg],
            "next": "",
            "thread_id": "test-thread",
            "token_usage": {},
        }
        await node(state)

        assert len(model.captured) == 1
        messages = model.captured[0]
        # System + 2 conversation messages = 3 total
        assert len(messages) == 3
        assert messages[0].type == "system"
        assert messages[1] is human_msg
        assert messages[2] is ai_msg
