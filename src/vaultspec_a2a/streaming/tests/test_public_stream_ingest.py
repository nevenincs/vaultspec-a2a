"""A run reaches its client through LangGraph's public stream API.

Ingest consumes ``astream`` over the documented stream modes with the tool
lifecycle taken from the callback surface beside it. Three properties of that
arrangement are what a client depends on:

- every family of frame a run produced before is still produced: model text,
  reasoning, tool lifecycle, node status and plan updates;
- a park is read from the stream as it happens, so a state read that fails
  afterwards can no longer turn an interrupted run into a completed one;
- nothing in the streaming package reaches into LangGraph's private modules
  to make any of it work.

Driven against real compiled graphs, a real checkpointer and the real event
producer; the model text comes from the deterministic lane, built through the
real provider factory.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING, Any, TypedDict, cast

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START
from langgraph.types import interrupt

from ...graph.enums import Provider, ToolCallStatus
from ...graph.events import (
    AgentStatus,
    ArtifactUpdate,
    MessageChunk,
    PermissionRequest,
    PlanUpdate,
    ToolCallStart,
    ToolCallUpdate,
)
from ...providers import ProviderFactory
from ...team.team_config import load_agent_config
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..aggregator import RunEventProducer
from ._relay_capture import relayed_events

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..types import StreamableGraph


class _State(TypedDict, total=False):
    note: str
    current_plan: list[dict[str, str]]


@tool
def write_report(file_path: str) -> str:
    """Write a report to *file_path*."""
    return f"wrote {file_path}"


def _speaking_node(
    replies: list[str],
) -> Callable[[_State], Awaitable[dict[str, Any]]]:
    """A node that thinks, answers, and writes a report, keeping its answer."""

    async def node(state: _State) -> dict[str, Any]:
        del state
        model = ProviderFactory().create(
            Provider.DETERMINISTIC,
            model="deterministic",
            agent_config=load_agent_config("vaultspec-researcher"),
        )
        answer = await model.ainvoke([HumanMessage(content="answer")])
        replies.append(str(answer.content))
        await write_report.ainvoke(
            {
                "name": "write_report",
                "args": {"file_path": "/work/report.md"},
                "id": "call_REPORT",
                "type": "tool_call",
            }
        )
        return {
            "note": "spoken",
            "current_plan": [{"content": "ship the report", "status": "pending"}],
        }

    return node


def _full_surface_graph(saver: AsyncSqliteSaver, replies: list[str]) -> StreamableGraph:
    builder = new_state_graph(_State)
    add_test_node(builder, "speaker", _speaking_node(replies))
    builder.add_edge(START, "speaker")
    builder.add_edge("speaker", END)
    return cast("StreamableGraph", compile_test_graph(builder, checkpointer=saver))


@pytest.mark.asyncio
async def test_a_run_still_reports_every_family_of_frame_it_used_to(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The public stream plus its callbacks carry the whole wire surface."""
    replies: list[str] = []
    producer = RunEventProducer()
    relayed = relayed_events(producer)
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", producer.ingest)

    outcome = await asyncio.wait_for(
        ingest(
            thread_id="thread-surface",
            agent_id="supervisor",
            graph=_full_surface_graph(checkpointer, replies),
            graph_input={"note": ""},
            config={"configurable": {"thread_id": "thread-surface"}},
        ),
        timeout=30.0,
    )

    assert outcome == "completed"
    events = [sequenced.event for sequenced in relayed]

    text = "".join(e.content for e in events if isinstance(e, MessageChunk))
    assert len(replies) == 1
    assert replies[0] in text

    starts = [e for e in events if isinstance(e, ToolCallStart)]
    assert [e.tool_call_id for e in starts] == ["call_REPORT"]
    assert starts[0].agent_id == "speaker"

    updates = [e for e in events if isinstance(e, ToolCallUpdate)]
    assert [e.tool_call_id for e in updates] == ["call_REPORT"]
    assert updates[0].status is ToolCallStatus.COMPLETED

    artifacts = [e for e in events if isinstance(e, ArtifactUpdate)]
    assert [e.filename for e in artifacts] == ["report.md"]

    statuses = [
        (e.node_name, e.state.value) for e in events if isinstance(e, AgentStatus)
    ]
    assert ("speaker", "working") in statuses
    assert ("speaker", "idle") in statuses
    # The node ran once, so it is reported working once: a nested runnable
    # inside it is not the node and must not report a second boundary.
    assert statuses.count(("speaker", "working")) == 1

    plans = [e.entries for e in events if isinstance(e, PlanUpdate)]
    assert plans == [
        [{"content": "ship the report", "status": "pending", "priority": "medium"}]
    ]


def _parking_graph(saver: AsyncSqliteSaver) -> StreamableGraph:
    async def gate(state: _State) -> dict[str, Any]:
        del state
        answer = interrupt(
            {
                "type": "permission_request",
                "request_id": "perm-parked-1",
                "tool_name": "fs/write_text_file",
            }
        )
        return {"note": str(answer)}

    builder = new_state_graph(_State)
    add_test_node(builder, "gate", gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    return cast("StreamableGraph", compile_test_graph(builder, checkpointer=saver))


@pytest.mark.asyncio
async def test_a_parked_run_is_reported_interrupted_and_asks_for_its_answer(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The stream reports the park, and the projection publishes the request."""
    producer = RunEventProducer()
    relayed = relayed_events(producer)
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", producer.ingest)

    outcome = await asyncio.wait_for(
        ingest(
            thread_id="thread-park",
            agent_id="supervisor",
            graph=_parking_graph(checkpointer),
            graph_input={"note": ""},
            config={"configurable": {"thread_id": "thread-park"}},
        ),
        timeout=30.0,
    )

    assert outcome == "interrupted"
    events = [sequenced.event for sequenced in relayed]
    requests = [e for e in events if isinstance(e, PermissionRequest)]
    assert requests, events
    assert "fs/write_text_file" in requests[0].description


_STREAMING_PACKAGE = pathlib.Path(__file__).resolve().parent.parent

_UNREADABLE_STATE_PROBE = textwrap.dedent(
    """
    import asyncio
    import json
    from typing import Any, TypedDict

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import END, START
    from langgraph.types import interrupt

    from vaultspec_a2a.streaming import RunEventProducer
    from vaultspec_a2a.streaming.ingest import GraphInvocation
    from vaultspec_a2a.testing import add_test_node, compile_test_graph, new_state_graph


    class S(TypedDict, total=False):
        note: str


    async def gate(state: S) -> dict[str, Any]:
        answer = interrupt(
        {"type": "permission_request", "request_id": "perm-deep-1", "tool_name": "deep"}
    )
        return {"note": str(answer)}


    async def main() -> dict[str, object]:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            await saver.setup()
            builder = new_state_graph(S)
            add_test_node(builder, "gate", gate)
            builder.add_edge(START, "gate")
            builder.add_edge("gate", END)
            graph = compile_test_graph(builder, checkpointer=saver)
            producer = RunEventProducer()
            emitted = []

            async def capture(sequenced):
                emitted.append(type(sequenced.event).__name__)

            producer.add_broadcast_hook(capture)
            outcome = await producer.ingest(
                "t", "supervisor", graph,
                GraphInvocation(
                    graph_input={"note": ""},
                    config={"configurable": {"thread_id": "t"}},
                ),
            )
            return {"outcome": outcome, "emitted": emitted}


    print(json.dumps(asyncio.run(main())))
    """
)


def test_a_park_survives_a_post_run_state_read_that_times_out() -> None:
    """An interrupted run is never reported completed because a read failed.

    The stream reports the park itself, so a post-run state read - which
    returns nothing on timeout - never decides whether the run is finished:
    were it to, the run would settle as though it had completed and write a
    terminal for a run sitting on a question. The read decides only whether
    the question can be published.

    The timeout knob is read once, when its module is imported, so this drives
    a real subprocess with the knob set below any real read's latency - the
    same recipe the state-projection knob's own test uses.
    """
    env = {
        **os.environ,
        "VAULTSPEC_A2A_AGET_STATE_TIMEOUT_SECONDS": "0.000001",
        "PYTHONPATH": str(_STREAMING_PACKAGE.parent.parent),
    }
    result = subprocess.run(
        [sys.executable, "-c", _UNREADABLE_STATE_PROBE],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed["outcome"] == "interrupted"
    # The read failed, so nothing could publish the question; the run's
    # outcome must not have depended on that.
    assert "PermissionRequest" not in observed["emitted"]


def test_the_streaming_package_reaches_into_no_private_langgraph_module() -> None:
    """The run is driven entirely by documented LangGraph surfaces.

    Consuming the v2 event API forced a private configuration key to be
    seated by hand so a shutdown drain could reach the loop at all, which
    made a rename in the library a silent loss of every drain request rather
    than an import error. Nothing here depends on a private module now, and
    this is what keeps it that way.
    """
    offenders: list[str] = []
    for path in sorted(_STREAMING_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            else:
                continue
            if module.startswith("langgraph.") and "._" in f".{module}":
                offenders.append(f"{path.name}: {module}")
    assert offenders == []
