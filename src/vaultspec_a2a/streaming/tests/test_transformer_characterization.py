"""Pin what each family of graph stream frame emits.

A run reaches a client through two surfaces: the graph's public stream modes
and the tool-lifecycle callbacks seated beside them. These characterize the
observable contract of both - given one frame or one callback, what wire
events reach a subscriber, and with what key fields.

Everything runs through the real event producer - real emitters, real
buffering, the real relay hook - with no mocks, so the assertions describe the
behaviour a client sees rather than the shape of the code.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from ...streaming import RunEventProducer
from ...streaming.transformer import StreamFrame

if TYPE_CHECKING:
    from ...streaming import SequencedEvent

_THREAD = "t-char"
_AGENT = "a-char"
_NODE = "researcher"

type _Frame = tuple[tuple[str, ...], str, object]
type _Drained = list[tuple[str, dict[str, Any]]]


async def _drive(
    frames: list[_Frame], callbacks: list[tuple[str, dict[str, Any]]] | None = None
) -> _Drained:
    """Feed frames and callbacks through the real producer and collect its relay."""
    producer = RunEventProducer()
    relayed: list[SequencedEvent] = []

    async def _capture(sequenced: SequencedEvent) -> None:
        relayed.append(sequenced)

    producer.add_broadcast_hook(_capture)
    handler = producer._ingest.run_lifecycle_callbacks(_THREAD, _AGENT)

    for namespace, mode, payload in frames:
        await producer._ingest.project_frame(
            StreamFrame(namespace=namespace, mode=mode, payload=payload),
            thread_id=_THREAD,
            agent_id=_AGENT,
        )
    for name, kwargs in callbacks or []:
        await getattr(handler, name)(**kwargs)
    await asyncio.sleep(0.05)

    # Every wire event is a dataclass, so its fields read uniformly through
    # dataclasses.asdict without depending on a serialisation method.
    return [
        (type(sequenced.event).__name__, asdict(sequenced.event))
        for sequenced in relayed
    ]


def _run(
    frames: list[_Frame], callbacks: list[tuple[str, dict[str, Any]]] | None = None
) -> _Drained:
    return asyncio.run(_drive(frames, callbacks))


def _stream(chunk: AIMessageChunk) -> _Frame:
    return ((), "messages", (chunk, {"langgraph_node": _NODE}))


def _llm_end(
    message: AIMessage, tags: list[str] | None = None
) -> tuple[str, dict[str, Any]]:
    return (
        "on_llm_end",
        {
            "response": LLMResult(generations=[[ChatGeneration(message=message)]]),
            "run_id": uuid4(),
            "tags": tags or [],
        },
    )


def test_a_string_content_chunk_becomes_a_buffered_message_chunk() -> None:
    """Plain text streams as a message chunk, flushed at model end."""
    emitted = _run(
        [_stream(AIMessageChunk(content="hello world", id="r1"))],
        [_llm_end(AIMessage(content="hello world", id="r1"))],
    )

    names = [name for name, _ in emitted]
    assert "MessageChunk" in names
    chunk = next(p for n, p in emitted if n == "MessageChunk")
    assert chunk["content"] == "hello world"
    assert chunk["agent_id"] == _NODE


def test_a_finish_reason_at_end_emits_a_terminal_message_chunk() -> None:
    """The model-end finish reason surfaces on a final empty chunk."""
    emitted = _run(
        [],
        [
            _llm_end(
                AIMessage(
                    content="", id="r1", response_metadata={"finish_reason": "stop"}
                )
            )
        ],
    )

    finals = [p for n, p in emitted if n == "MessageChunk" and p.get("finish_reason")]
    assert finals, emitted
    assert finals[0]["finish_reason"] == "stop"


def test_a_tool_start_emits_a_tool_call_start() -> None:
    """A tool invocation inside a node surfaces to the client."""
    emitted = _run(
        [],
        [
            (
                "on_tool_start",
                {
                    "serialized": {"name": "vaultspec-rag"},
                    "input_str": "{'query': 'x'}",
                    "run_id": uuid4(),
                    "metadata": {"langgraph_node": _NODE},
                    "inputs": {"query": "x"},
                    "tool_call_id": "call_RAG",
                },
            )
        ],
    )

    starts = [p for n, p in emitted if n == "ToolCallStart"]
    assert starts, emitted
    assert starts[0]["tool_call_id"] == "call_RAG"
    assert starts[0]["agent_id"] == _NODE


def test_a_tool_end_resolves_the_call_the_start_registered() -> None:
    """One tool call carries one identity from registration to resolution."""
    run_id = uuid4()
    emitted = _run(
        [],
        [
            (
                "on_tool_start",
                {
                    "serialized": {"name": "vaultspec-rag"},
                    "input_str": "{}",
                    "run_id": run_id,
                    "metadata": {"langgraph_node": _NODE},
                    "inputs": {"query": "x"},
                    "tool_call_id": "call_RAG",
                },
            ),
            (
                "on_tool_end",
                {
                    "output": ToolMessage(
                        content="hit", name="vaultspec-rag", tool_call_id="call_RAG"
                    ),
                    "run_id": run_id,
                    "tool_call_id": "call_RAG",
                },
            ),
        ],
    )

    identities = {
        p["tool_call_id"]
        for n, p in emitted
        if n in ("ToolCallStart", "ToolCallUpdate")
    }
    assert identities == {"call_RAG"}


def test_a_reasoning_block_chunk_emits_a_thought_chunk() -> None:
    """A reasoning content block streams as a thought, not a message."""
    chunk = AIMessageChunk(
        content=[{"type": "reasoning", "content": "thinking about it"}], id="r1"
    )

    emitted = _run([_stream(chunk)])

    thoughts = [p for n, p in emitted if n == "ThoughtChunk"]
    assert thoughts, emitted
    assert thoughts[0]["content"] == "thinking about it"


def test_text_delta_block_is_buffered_as_message_content() -> None:
    emitted = _run(
        [
            _stream(
                AIMessageChunk(
                    content=[{"type": "text_delta", "text": "hello"}], id="r1"
                )
            )
        ],
        [_llm_end(AIMessage(content="hello", id="r1"))],
    )

    messages = [payload for name, payload in emitted if name == "MessageChunk"]
    assert any(payload["content"] == "hello" for payload in messages)


def test_additional_reasoning_emits_once_without_content_blocks() -> None:
    emitted = _run(
        [
            _stream(
                AIMessageChunk(
                    content="",
                    id="r1",
                    additional_kwargs={"reasoning_content": "thinking separately"},
                )
            )
        ]
    )

    thoughts = [payload for name, payload in emitted if name == "ThoughtChunk"]
    assert [payload["content"] for payload in thoughts] == ["thinking separately"]


def test_a_frame_of_a_mode_this_projection_ignores_emits_nothing() -> None:
    """A mode consumed for the run's own classification produces no wire event."""
    emitted = _run([((), "updates", {"researcher": {"note": "x"}})])

    assert emitted == []


def test_chunks_share_the_message_id_so_a_client_can_join_them() -> None:
    """Two chunks of one model turn carry one message id.

    The model's own message id is used, not the run id behind it, because
    that same id is what the settled run's REST snapshot reports for the
    message these chunks make up.
    """
    emitted = _run(
        [
            _stream(AIMessageChunk(content="part one ", id="msg-A")),
            _stream(AIMessageChunk(content="part two", id="msg-A")),
        ],
        [_llm_end(AIMessage(content="part one part two", id="msg-A"))],
    )

    message_ids = {p["message_id"] for n, p in emitted if n == "MessageChunk"}
    assert message_ids == {"msg-A"}, emitted
