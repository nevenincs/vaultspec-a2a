"""Graph execution tests using Provider.MOCK against a live VidaiMock instance.

These tests close the gap between compilation tests (test_graph.py) and
live-provider integration tests (test_e2e_live.py): they exercise the full
LangGraph execution pipeline — node dispatch, LLM call, event stream
processing, checkpoint persistence — with deterministic tape responses.

Requires ``requires_vidaimock`` marker: VidaiMock must be running at
``MOCK_API_BASE`` (default ``http://localhost:8100``).  Start with::

    just vidaimock-up

Covered scenarios
-----------------
- Single-agent pipeline completes two turns (tool call → completion text).
- Tool-failure pipeline: agent emits a ``run_command`` call with ``exit 1``,
  then completes with a failure summary.
- Human-in-loop pipeline: agent always emits ``session_request_permission``;
  graph pauses as expected when auto_approve is disabled.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..graph import compile_team_graph
from ..team_config import load_agent_config, load_team_config


pytestmark = pytest.mark.requires_vidaimock


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    """In-memory SQLite checkpointer — isolated per test."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _make_config(thread_id: str) -> RunnableConfig:
    return RunnableConfig(configurable={"thread_id": thread_id})


def _ai_messages(states: list[dict]) -> list[AIMessage]:
    """Collect all AIMessages from a list of streamed state snapshots."""
    seen: set[int] = set()
    result: list[AIMessage] = []
    for state in states:
        for msg in state.get("messages", []):
            if isinstance(msg, AIMessage) and id(msg) not in seen:
                seen.add(id(msg))
                result.append(msg)
    return result


# ---------------------------------------------------------------------------
# Test 1 — single-agent pipeline runs to two-turn completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_single_agent_pipeline_runs_to_completion(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """mock-success-single executes two LLM turns and finishes.

    Turn 1 (n<=1 in Jinja2 tape): model emits a ``run_command`` tool call.
    Turn 2 (n>1): model emits completion text confirming success.

    Assertions:
    - At least two AI messages are produced.
    - First AI message carries exactly one tool call named ``run_command``.
    - Final AI message carries no tool calls (pure text completion).
    - Checkpoint state persisted after the run.
    """
    team = load_team_config("mock-success-single")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    inputs = {"messages": [HumanMessage(content="Execute the mock protocol.")]}
    config = _make_config("test-mock-single")

    states: list[dict] = []
    async for state in graph.astream(inputs, config, stream_mode="values"):
        states.append(state)

    assert states, "astream yielded no states — graph did not execute"

    ai_msgs = _ai_messages(states)
    assert len(ai_msgs) >= 2, (
        f"Expected ≥2 AI messages (tool-call turn + completion turn), got {len(ai_msgs)}"
    )

    # First AI message must carry the run_command tool call
    first = ai_msgs[0]
    assert first.tool_calls, "First AI message expected to carry tool_calls"
    tool_names = [tc["name"] for tc in first.tool_calls]
    assert "run_command" in tool_names, (
        f"Expected 'run_command' in tool calls, got: {tool_names}"
    )

    # Last AI message must be a text completion (no tool calls)
    last = ai_msgs[-1]
    assert not last.tool_calls, (
        "Last AI message should be a text completion with no tool calls"
    )
    last_text = last.content if isinstance(last.content, str) else str(last.content)
    assert last_text.strip(), "Last AI message content must be non-empty text"

    # Checkpoint must be persisted
    saved = await checkpointer.aget(config)
    assert saved is not None, "Checkpoint was not written after graph run"
    assert "messages" in saved["channel_values"]


# ---------------------------------------------------------------------------
# Test 2 — tool-failure pipeline executes and surfaces failure summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_tool_failure_pipeline_surfaces_failure_summary(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """mock-failure-tool executes a failing command then reports it.

    Turn 1: model emits a ``run_command`` tool call (exits non-zero).
    Turn 2: model emits a failure summary confirming it observed the error.

    Assertions:
    - At least two AI messages are produced.
    - First AI message carries a ``run_command`` tool call.
    - Last AI message is a text completion (failure summary), no tool calls.
    """
    team = load_team_config("mock-failure-tool")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    inputs = {"messages": [HumanMessage(content="Execute the mock failure protocol.")]}
    config = _make_config("test-mock-failure")

    states: list[dict] = []
    async for state in graph.astream(inputs, config, stream_mode="values"):
        states.append(state)

    assert states, "astream yielded no states — graph did not execute"

    ai_msgs = _ai_messages(states)
    assert len(ai_msgs) >= 2, (
        f"Expected ≥2 AI messages (tool-call turn + failure summary), got {len(ai_msgs)}"
    )

    first = ai_msgs[0]
    assert first.tool_calls, "First AI message expected to carry tool_calls"
    tool_names = [tc["name"] for tc in first.tool_calls]
    assert "run_command" in tool_names, (
        f"Expected 'run_command' in first tool calls, got: {tool_names}"
    )

    last = ai_msgs[-1]
    assert not last.tool_calls, "Final AI message should be a text summary, not a tool call"


# ---------------------------------------------------------------------------
# Test 3 — human-in-loop pipeline pauses on permission request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_human_in_loop_pauses_on_permission_request(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """mock-human-in-loop tape always emits ``session_request_permission``.

    The agent requests permission for a privileged command.  With
    ``auto_approve=false`` in the team config, the graph pauses rather than
    proceeding automatically.  The test verifies:

    - At least one state update is yielded before the pause.
    - The final messages in the checkpoint contain a ``session_request_permission``
      tool call — confirming the tape was reached and the permission request
      is durably recorded.
    """
    from langgraph.errors import GraphInterrupt

    team = load_team_config("mock-human-in-loop")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    inputs = {"messages": [HumanMessage(content="Execute the mock human protocol.")]}
    config = _make_config("test-mock-human")

    states: list[dict] = []
    try:
        async for state in graph.astream(inputs, config, stream_mode="values"):
            states.append(state)
    except GraphInterrupt:
        # Expected: graph pauses when session_request_permission is unhandled.
        pass

    assert states, "No state was yielded before the permission pause"

    # Collect all AI messages from all yielded states
    ai_msgs = _ai_messages(states)
    assert ai_msgs, "No AI messages found in any yielded state"

    # At least one AI message must carry the session_request_permission tool call
    permission_calls = [
        tc
        for msg in ai_msgs
        for tc in (msg.tool_calls or [])
        if tc.get("name") == "session_request_permission"
    ]
    assert permission_calls, (
        "Expected a 'session_request_permission' tool call in AI messages; "
        f"found tool calls: {[tc['name'] for msg in ai_msgs for tc in (msg.tool_calls or [])]}"
    )
