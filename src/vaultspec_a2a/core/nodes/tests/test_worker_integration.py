"""Integration tests for the worker node using the ACP simulator.

These tests replace the legacy stub-based tests with high-fidelity integration
tests that use a real AcpChatModel pointing to a local simulator process.
"""

import sys

from pathlib import Path

import pytest

from langchain_core.messages import BaseMessage, HumanMessage

from ....providers.acp_chat_model import AcpChatModel
from ...state import TeamState
from ..worker import create_worker_node


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


@pytest.mark.asyncio
async def test_worker_execution_integration() -> None:
    """Worker node executes correctly using a real ACP subprocess (integration)."""
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
    """Worker node handles large context with compaction (integration)."""
    model = AcpChatModel(
        command=[PYTHON_EXE, str(SIMULATOR_PATH), "--response", "Compacted"],
        env_vars={},
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    # Large content to trigger compaction (120k tokens threshold)
    big_messages: list[BaseMessage] = [HumanMessage(content="x" * 500_000)]
    state = _make_state()
    state["messages"] = big_messages

    result = await node(state)
    assert result["messages"][0].content == "Compacted"


@pytest.mark.asyncio
async def test_worker_error_handling_integration() -> None:
    """Worker node handles ACP subprocess errors correctly (integration)."""
    # Use the simulator to return an error
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

    # AcpChatModel raises AcpPromptError, which is wrapped in WorkerExecutionError
    error_str = str(excinfo.value)
    if excinfo.value.__cause__:
        error_str += " " + str(excinfo.value.__cause__)

    assert "Internal agent failure" in error_str
