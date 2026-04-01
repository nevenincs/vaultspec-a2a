"""Integration tests for the worker node using the ACP simulator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command
from pydantic import PrivateAttr

from vaultspec_a2a.thread.state import TeamState

from ...nodes.worker import create_worker_node

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

SIMULATOR_PATH = Path(__file__).parent.parent / "acp_simulator.py"
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


class RecordingMockPermissionModel(BaseChatModel):
    """Minimal in-memory model that exercises the worker permission replay path."""

    permission_callback: Any | None = None
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("RecordingMockPermissionModel only supports async")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._calls.append(list(messages))
        if messages and isinstance(messages[-1], ToolMessage):
            response = AIMessage(content="approved path")
        else:
            response = AIMessage(
                content="Requesting permission",
                tool_calls=[
                    {
                        "id": "call_0",
                        "name": "session_request_permission",
                        "args": {
                            "description": "Run a privileged command",
                            "options": [
                                {"optionId": "approve"},
                                {"optionId": "reject_once"},
                            ],
                        },
                        "type": "tool_call",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=response)])


@pytest.mark.asyncio
async def test_worker_execution_integration() -> None:
    """Worker node executes correctly using a real ACP subprocess."""
    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

    model = AcpChatModel(
        command=[PYTHON_EXE, str(SIMULATOR_PATH), "--response", "HelloWorld"],
        env_vars={},
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    result = await node(_make_state())
    assert "messages" in result
    assert result["messages"][0].content == "HelloWorld"
    assert result["messages"][0].name == "coder"


@pytest.mark.asyncio
async def test_worker_context_compaction_integration() -> None:
    """Worker node handles large context with compaction."""
    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

    model = AcpChatModel(
        command=[PYTHON_EXE, str(SIMULATOR_PATH), "--response", "Compacted"],
        env_vars={},
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    big_messages: list[BaseMessage] = [HumanMessage(content="x" * 500_000)]
    state = _make_state()
    state["messages"] = big_messages

    result = await node(state)
    assert result["messages"][0].content == "Compacted"


@pytest.mark.asyncio
async def test_worker_error_handling_integration() -> None:
    """Worker node handles ACP subprocess errors correctly."""
    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

    model = AcpChatModel(
        command=[PYTHON_EXE, str(SIMULATOR_PATH), "--error", "Internal agent failure"],
        env_vars={},
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    with pytest.raises(Exception) as excinfo:
        await node(_make_state())

    error_str = str(excinfo.value)
    if excinfo.value.__cause__:
        error_str += " " + str(excinfo.value.__cause__)

    assert "Internal agent failure" in error_str


@pytest.mark.asyncio
async def test_worker_resume_reinvokes_model_with_tool_result() -> None:
    """Resuming after interrupt should trigger the post-approval second model call."""
    model = RecordingMockPermissionModel()
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    builder = StateGraph(cast("Any", TeamState))
    builder.add_node("coder", node)
    builder.set_entry_point("coder")
    builder.add_edge("coder", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "test-worker-resume"}}

    first_result = await graph.ainvoke(_make_state(), config=config)
    assert "__interrupt__" in first_result

    resumed = await graph.ainvoke(Command(resume="approve"), config=config)
    final_message = resumed["messages"][-1]
    assert final_message.content == "approved path"
    assert final_message.name == "coder"

    assert len(model.calls) == 3
    follow_up_messages = model.calls[-1]
    assert isinstance(follow_up_messages[-1], ToolMessage)
    assert follow_up_messages[-1].tool_call_id == "call_0"
    assert follow_up_messages[-1].content == '{"approved_option_id": "approve"}'
    assert "Human approval has been resolved" in str(follow_up_messages[-3].content)
