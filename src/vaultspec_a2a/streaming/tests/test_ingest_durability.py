"""A run ingest starts persists each superstep before the next one begins.

Recovery is checkpoint-first: a redelivered action is judged against the last
committed checkpoint, and a pre-flight that reads a superstep LangGraph had
only scheduled would re-run work the checkpoint does not know happened. The
mode that guarantees the order is ``durability="sync"``; LangGraph's default is
``"async"``, which persists "while the next step executes".

The proof is an ordering one, so it needs a checkpointer whose write takes
observable time. ``_TimedSqliteSaver`` is a real ``AsyncSqliteSaver`` -- it
performs the real write against a real SQLite database -- that records when
each write starts and ends and holds a real delay in between, the way a loaded
database would. The nodes record when they run into the same log, so the log
says whether the second node started before or after the first superstep's
write landed.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict, cast, override

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START
from langgraph.types import Command, interrupt

from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..aggregator import RunEventProducer

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import (
        ChannelVersions,
        Checkpoint,
        CheckpointMetadata,
    )

    from ..types import StreamableGraph

#: Long enough that a write still in flight cannot be mistaken for one that
#: landed, short enough to keep the test quick.
_WRITE_DELAY_SECONDS = 0.25


class _State(TypedDict):
    note: str


class _TimedSqliteSaver(AsyncSqliteSaver):
    """A real SQLite saver that takes real time to write, and says when.

    Only the timing is added: every checkpoint is written by the real saver to
    the real database. The delay exists so the ordering guarantee under test is
    observable at all -- against an instantaneous write, a run that persists
    "while the next step executes" and one that persists "before the next step
    starts" produce the same log.
    """

    def __init__(self, conn: Any, log: list[str]) -> None:
        super().__init__(conn)
        self._log = log

    @override
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        step = metadata.get("step")
        self._log.append(f"write-start:{step}")
        await asyncio.sleep(_WRITE_DELAY_SECONDS)
        result = await super().aput(config, checkpoint, metadata, new_versions)
        self._log.append(f"write-end:{step}")
        return result


def _two_step_graph(saver: AsyncSqliteSaver, log: list[str]) -> StreamableGraph:
    async def first(state: _State) -> dict[str, str]:
        del state
        log.append("node:first")
        return {"note": "first"}

    async def second(state: _State) -> dict[str, str]:
        del state
        log.append("node:second")
        return {"note": "second"}

    builder = new_state_graph(_State)
    add_test_node(builder, "first", first)
    add_test_node(builder, "second", second)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    return cast("StreamableGraph", compile_test_graph(builder, checkpointer=saver))


@pytest.mark.asyncio
async def test_ingest_commits_each_superstep_before_the_next_one_starts(
    checkpointer: AsyncSqliteSaver,
) -> None:
    log: list[str] = []
    saver = _TimedSqliteSaver(checkpointer.conn, log)
    await saver.setup()
    graph = _two_step_graph(saver, log)
    producer = RunEventProducer()
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", producer.ingest)

    outcome = await asyncio.wait_for(
        ingest(
            thread_id="thread-durability",
            agent_id="supervisor",
            graph=graph,
            graph_input={"note": ""},
            config={"configurable": {"thread_id": "thread-durability"}},
        ),
        timeout=30.0,
    )

    assert outcome == "completed"
    assert "node:first" in log
    assert "node:second" in log
    # The superstep that ran `first` is step 0; `second` must not start until
    # that write has landed.
    assert log.index("write-end:0") < log.index("node:second"), log


def _gated_graph(saver: AsyncSqliteSaver, log: list[str]) -> StreamableGraph:
    async def gate(state: _State) -> dict[str, str]:
        del state
        answer = interrupt(
            {
                "type": "permission_request",
                "request_id": "probe-permission",
                "tool_name": "probe",
            }
        )
        log.append("node:gate")
        return {"note": str(answer)}

    async def after(state: _State) -> dict[str, str]:
        del state
        log.append("node:after")
        return {"note": "after"}

    builder = new_state_graph(_State)
    add_test_node(builder, "gate", gate)
    add_test_node(builder, "after", after)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", "after")
    builder.add_edge("after", END)
    return cast("StreamableGraph", compile_test_graph(builder, checkpointer=saver))


@pytest.mark.asyncio
async def test_a_resume_commits_its_superstep_before_the_next_one_starts(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A resumed turn persists on the same terms as the turn that parked.

    A resume is where checkpoint-first recovery matters most: the run already
    survived one park, and the answer a human gave must be durable before the
    work it unblocks runs, or a crash replays the gate with the answer lost.
    """
    log: list[str] = []
    config = {"configurable": {"thread_id": "thread-durability-resume"}}
    saver = _TimedSqliteSaver(checkpointer.conn, log)
    await saver.setup()
    graph = _gated_graph(saver, log)
    producer = RunEventProducer()
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", producer.ingest)

    parked = await asyncio.wait_for(
        ingest(
            thread_id="thread-durability-resume",
            agent_id="supervisor",
            graph=graph,
            graph_input={"note": ""},
            config=config,
        ),
        timeout=30.0,
    )
    assert parked == "interrupted"
    log.append("--resumed--")

    resumed = await asyncio.wait_for(
        ingest(
            thread_id="thread-durability-resume",
            agent_id="supervisor",
            graph=graph,
            graph_input=Command(resume="allow_once"),
            config=config,
        ),
        timeout=30.0,
    )

    assert resumed == "completed"
    resume_log = log[log.index("--resumed--") :]
    assert "node:gate" in resume_log
    assert "node:after" in resume_log
    # Every write the resumed turn started had landed before the next node
    # ran, so no superstep of it was still in flight while its successor
    # executed.
    in_flight = 0
    for entry in resume_log[: resume_log.index("node:after")]:
        if entry.startswith("write-start:"):
            in_flight += 1
        elif entry.startswith("write-end:"):
            in_flight -= 1
    assert in_flight == 0, resume_log
