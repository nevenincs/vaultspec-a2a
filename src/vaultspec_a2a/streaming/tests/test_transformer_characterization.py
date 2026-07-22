"""Pin what each LangGraph event family emits, before it is decomposed.

The transformer's ``process_langgraph_event`` is a single long function with one
branch per event family. It has no direct tests - only the aggregator suite
exercises it indirectly - which makes it exactly the code a refactor can change
without anyone noticing.

These characterize the observable contract: given one LangGraph callback event,
what wire events reach a subscriber, and with what key fields. Everything runs
through the real aggregator - real emitters, real buffering, real subscriber
queue - with no mocks, so the assertions describe the behaviour a client sees
rather than the shape of the code.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk

from vaultspec_a2a.streaming.aggregator import EventAggregator

_THREAD = "t-char"
_AGENT = "a-char"
_NODE = "researcher"


async def _drive(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Feed events through the real aggregator and drain the subscriber queue."""
    aggregator = EventAggregator()
    queue = aggregator.add_subscriber("client")
    aggregator.subscribe("client", [_THREAD])

    for event in events:
        await aggregator.process_langgraph_event(
            event, thread_id=_THREAD, agent_id=_AGENT
        )
    await asyncio.sleep(0.05)

    drained: list[tuple[str, dict[str, Any]]] = []
    while not queue.empty():
        sequenced = queue.get_nowait()
        event = sequenced.event
        # Every wire event is a dataclass, so its fields read uniformly through
        # dataclasses.asdict without depending on a serialisation method.
        drained.append((type(event).__name__, asdict(event)))
    return drained


def _run(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return asyncio.run(_drive(events))


def _stream(chunk: AIMessageChunk, run_id: str = "r1") -> dict[str, Any]:
    return {
        "event": "on_chat_model_stream",
        "run_id": run_id,
        "metadata": {"langgraph_node": _NODE},
        "data": {"chunk": chunk},
    }


def _end(output: Any = None, run_id: str = "r1") -> dict[str, Any]:
    return {
        "event": "on_chat_model_end",
        "run_id": run_id,
        "metadata": {"langgraph_node": _NODE},
        "data": {"output": output},
    }


def test_a_string_content_chunk_becomes_a_buffered_message_chunk() -> None:
    """Plain text streams as a message chunk, flushed at model end."""
    emitted = _run([_stream(AIMessageChunk(content="hello world")), _end()])

    names = [name for name, _ in emitted]
    assert "MessageChunk" in names
    chunk = next(p for n, p in emitted if n == "MessageChunk")
    assert chunk["content"] == "hello world"
    assert chunk["agent_id"] == _NODE


def test_a_finish_reason_at_end_emits_a_terminal_message_chunk() -> None:
    """The model-end finish reason surfaces on a final empty chunk."""
    output = AIMessage(content="", response_metadata={"finish_reason": "stop"})

    emitted = _run([_end(output=output)])

    finals = [p for n, p in emitted if n == "MessageChunk" and p.get("finish_reason")]
    assert finals, emitted
    assert finals[0]["finish_reason"] == "stop"


def test_a_tool_start_on_a_node_emits_a_tool_call_start() -> None:
    """A tool invocation inside a node surfaces to the client."""
    emitted = _run(
        [
            {
                "event": "on_tool_start",
                "run_id": "r-tool",
                "name": "vaultspec-rag",
                "metadata": {"langgraph_node": _NODE},
                "data": {"input": {"query": "x"}},
            }
        ]
    )

    assert any(name == "ToolCallStart" for name, _ in emitted), emitted


def test_a_reasoning_block_chunk_emits_a_thought_chunk() -> None:
    """A reasoning content block streams as a thought, not a message."""
    chunk = AIMessageChunk(
        content=[{"type": "reasoning", "content": "thinking about it"}]
    )

    emitted = _run([_stream(chunk)])

    thoughts = [p for n, p in emitted if n == "ThoughtChunk"]
    assert thoughts, emitted
    assert thoughts[0]["content"] == "thinking about it"


def test_an_event_without_a_node_and_no_family_emits_nothing() -> None:
    """A sub-runnable event with no matching family is filtered out."""
    emitted = _run(
        [{"event": "on_chain_start", "run_id": "r", "metadata": {}, "data": {}}]
    )

    assert emitted == []


def test_chunks_share_the_run_id_as_message_id() -> None:
    """Two chunks of one model run carry one message id, so a client can join them."""
    emitted = _run(
        [
            _stream(AIMessageChunk(content="part one "), run_id="run-A"),
            _stream(AIMessageChunk(content="part two"), run_id="run-A"),
            _end(run_id="run-A"),
        ]
    )

    message_ids = {p["message_id"] for n, p in emitted if n == "MessageChunk"}
    assert message_ids == {"run-A"}, emitted
