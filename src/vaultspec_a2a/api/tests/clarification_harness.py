"""Shared real-behavior harness for clarification API tests.

The harness owns one minimal graph topology that raises the real clarification
interrupt and a loopback callback server for a normally constructed worker
bridge.  Endpoint and worker-loop tests therefore exercise the same graph and
checkpoint boundary without importing private helpers from one another.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, cast

import anyio
import uvicorn
from fastapi import FastAPI
from langchain_core.messages import HumanMessage

from ...graph.nodes.clarification import (
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ...thread.clarification import (
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
    pending_clarification,
)
from ...thread.state import TeamState
from ...worker.graph_lifecycle import RegisteredCompiledGraph
from ...worker.ipc import WorkerBridge

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command

    from ...database.checkpoints import Checkpointer

__all__ = [
    "ClarificationGraph",
    "ParkedClarification",
    "clarification_graph",
    "loopback_callback_bridge",
    "new_state_graph",
    "park_clarification",
]


type ClarificationNode = Literal[
    "clarification_request", "clarification_gate", "complete"
]
type ClarificationCommand = Command[ClarificationNode]


class ClarificationGraph(RegisteredCompiledGraph, Protocol):
    """Compiled graph surface the shared clarification tests exercise."""


class ClarificationGraphBuilder(Protocol):
    """Shared graph-construction surface for real worker test graphs."""

    def add_node(self, node: str, action: object) -> None: ...

    def add_edge(self, start_key: str, end_key: str) -> None: ...

    def compile(self, *, checkpointer: Checkpointer) -> RegisteredCompiledGraph: ...


class _GraphState(Protocol):
    """Structural state bound used only while constructing the real graph.

    These two metadata attributes are LangGraph's TypedDict bound, not copied
    application state fields. ``TeamState`` remains the actual runtime schema.
    """

    __required_keys__: ClassVar[frozenset[str]]
    __optional_keys__: ClassVar[frozenset[str]]


class _StateGraphConstructor(Protocol):
    """Runtime-loaded LangGraph constructor narrowed to this harness's needs."""

    def __call__(
        self, state_schema: type[_GraphState]
    ) -> ClarificationGraphBuilder: ...


def new_state_graph() -> ClarificationGraphBuilder:
    """Construct a real LangGraph builder behind this harness's typed boundary."""
    graph_module = import_module("langgraph.graph")
    state_graph = getattr(graph_module, "StateGraph", None)
    assert callable(state_graph)
    state_graph_constructor = cast("_StateGraphConstructor", state_graph)
    return state_graph_constructor(cast("type[_GraphState]", TeamState))


class BoundSocket(Protocol):
    """Socket surface needed to discover Uvicorn's ephemeral bound port."""

    def getsockname(self) -> tuple[object, ...]: ...


class BoundServer(Protocol):
    """Uvicorn listener surface exposed after startup."""

    sockets: list[BoundSocket] | None


@dataclass(frozen=True)
class ParkedClarification:
    """The real graph and its typed request after a durable interruption."""

    graph: ClarificationGraph
    request: ClarificationRequest


async def _produce_questions(state: TeamState) -> ClarificationRequest:
    """Provide the concrete questionnaire for this real graph exercise.

    The parameter remains named ``state`` because the producer protocol requires
    that keyword-compatible name at the graph-construction boundary.
    """
    del state
    return ClarificationRequest(
        request_id="clarification-endpoint-request",
        questions=[
            ClarificationQuestion(
                id="provider",
                prompt="Which provider should author the plan?",
                kind=ClarificationKind.CHOICE,
                options=["codex", "zai"],
            ),
            ClarificationQuestion(
                id="scope",
                prompt="Which module should this target?",
                kind=ClarificationKind.TEXT,
                required=False,
            ),
        ],
    )


def _complete(state: TeamState) -> dict[str, object]:
    """Terminate the purpose-built graph after a successful clarification."""
    del state
    return {}


def clarification_graph(checkpointer: AsyncSqliteSaver) -> ClarificationGraph:
    """Compile the shared minimal graph around the real clarification nodes."""
    builder = new_state_graph()
    builder.add_node(
        "clarification_request",
        create_clarification_request_node(
            _produce_questions,
            gate_target="clarification_gate",
            proceed_target="complete",
        ),
    )
    builder.add_node(
        "clarification_gate",
        create_clarification_gate_node(proceed_target="complete"),
    )
    builder.add_node("complete", _complete)
    builder.add_edge("__start__", "clarification_request")
    builder.add_edge("complete", "__end__")
    return cast("ClarificationGraph", builder.compile(checkpointer=checkpointer))


async def park_clarification(
    checkpointer: AsyncSqliteSaver, *, thread_id: str
) -> ParkedClarification:
    """Park the shared graph and return its checkpoint-authoritative request."""
    graph = clarification_graph(checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    state: TeamState = {
        "active_agent": "clarification",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Ground the feature.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "agent-panel",
        "token_usage": {},
    }
    await graph.ainvoke(state, config=config)
    request = pending_clarification(
        await checkpointer.aget_tuple(config), thread_id=thread_id
    )
    assert request is not None, "clarification graph did not park"
    return ParkedClarification(graph=graph, request=request)


async def _accept_event_batch() -> dict[str, str]:
    """Accept the bridge's real batched callback payload."""
    return {"status": "ok"}


async def _accept_heartbeat() -> dict[str, str]:
    """Accept the bridge's real heartbeat callback payload."""
    return {"status": "ok"}


@asynccontextmanager
async def loopback_callback_bridge() -> AsyncGenerator[WorkerBridge]:
    """Serve worker callbacks on an ephemeral loopback listener.

    ``WorkerBridge`` remains normally constructed with its production HTTP
    client; only the callback destination is local to this focused test.
    """
    app = FastAPI()
    app.add_api_route(
        "/internal/events/batch",
        _accept_event_batch,
        methods=["POST"],
    )
    app.add_api_route("/internal/heartbeat", _accept_heartbeat, methods=["POST"])

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            lifespan="off",
            log_config=None,
        )
    )
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(server.serve)
        with anyio.fail_after(5.0):
            while not server.started:
                await anyio.sleep(0.01)

        servers = cast("list[BoundServer]", server.servers)
        assert servers
        listeners = servers[0].sockets
        assert listeners is not None
        socket = listeners[0]
        address = socket.getsockname()
        assert isinstance(address, tuple)
        assert len(address) >= 2
        port = address[1]
        assert isinstance(port, int)
        bridge = WorkerBridge(
            api_url=f"http://127.0.0.1:{port}",
            worker_id="clarification-loop-worker",
        )
        try:
            yield bridge
        finally:
            await bridge.close()
            server.should_exit = True
