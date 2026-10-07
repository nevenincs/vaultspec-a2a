"""Shared real-behavior harness for clarification API tests.

The harness owns one minimal graph topology that raises the real clarification
interrupt. Endpoint and worker-loop tests therefore exercise the same graph and
checkpoint boundary without importing private helpers from one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, cast

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

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.base import BaseStore
    from langgraph.types import Command

    from ...database.checkpoints import Checkpointer

__all__ = [
    "clarification_graph",
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

    def compile(
        self, *, checkpointer: Checkpointer, store: BaseStore | None = None
    ) -> RegisteredCompiledGraph: ...


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
    return builder.compile(checkpointer=checkpointer)


async def park_clarification(
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    model_assignment_digest: str | None = None,
    graph_definition_digest: str | None = None,
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
    if model_assignment_digest is not None:
        state["model_assignment_digest"] = model_assignment_digest
    if graph_definition_digest is not None:
        state["graph_definition_digest"] = graph_definition_digest
    await graph.ainvoke(state, config=config)
    request = pending_clarification(
        await checkpointer.aget_tuple(config), thread_id=thread_id
    )
    assert request is not None, "clarification graph did not park"
    return ParkedClarification(graph=graph, request=request)
