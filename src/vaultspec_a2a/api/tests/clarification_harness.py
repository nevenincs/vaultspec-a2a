"""Shared real-behavior harness for clarification API tests.

The harness owns one minimal graph topology that raises the real clarification
interrupt. Endpoint and worker-loop tests therefore exercise the same graph and
checkpoint boundary without importing private helpers from one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from langchain_core.messages import HumanMessage

from ...graph.nodes.clarification import (
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...thread import project_checkpoint_tuple
from ...thread.clarification import (
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
    pending_clarification,
)
from ...worker.graph_lifecycle import RegisteredCompiledGraph

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command

    from ...thread.state import TeamState


__all__ = [
    "clarification_graph",
    "park_clarification",
]


type ClarificationNode = Literal[
    "clarification_request", "clarification_gate", "complete"
]
type ClarificationCommand = Command[ClarificationNode]


class ClarificationGraph(RegisteredCompiledGraph, Protocol):
    """Compiled graph surface the shared clarification tests exercise."""


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
    add_test_node(
        builder,
        "clarification_request",
        create_clarification_request_node(
            _produce_questions,
            gate_target="clarification_gate",
            proceed_target="complete",
        ),
    )
    add_test_node(
        builder,
        "clarification_gate",
        create_clarification_gate_node(proceed_target="complete"),
    )
    add_test_node(builder, "complete", _complete)
    builder.add_edge("__start__", "clarification_request")
    builder.add_edge("complete", "__end__")
    return compile_test_graph(builder, checkpointer=checkpointer)


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
    stored = await checkpointer.aget_tuple(config)
    assert stored is not None, "clarification graph wrote no checkpoint"
    request = pending_clarification(
        project_checkpoint_tuple(stored, thread_id=thread_id)
    )
    assert request is not None, "clarification graph did not park"
    return ParkedClarification(graph=graph, request=request)
