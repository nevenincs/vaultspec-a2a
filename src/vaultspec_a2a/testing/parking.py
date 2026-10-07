"""Real runs parked on the real interrupts a respond verb answers.

A respond verb reads what a run is parked on from the run's checkpoint, so a test
that answers a request has to park a run on it first. These helpers park a real
graph over a real checkpointer on the interrupts each producer raises: a tool
permission raised by the worker's own permission callback, a plan approval raised
by the supervisor's own approval node, a document approval raised by a phase gate
and a clarification raised by the clarification nodes. The request id is the one
its producer named it, read back from the checkpoint rather than chosen by the
test.

A tool permission is also journaled the way the relay journals it, beside the
checkpoint that makes it answerable, for a test whose gateway reads both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START

from ..database import record_permission_request
from ..graph.nodes._worker_permissions import (
    permission_callback_for,
    recorded_permission_answers,
)
from ..graph.nodes.clarification import (
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ..graph.nodes.phase_gate import create_phase_gate_node, create_phase_submit_node
from ..graph.nodes.supervisor import create_plan_approval_node
from ..thread import project_checkpoint_tuple
from ..thread.clarification import (
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
    pending_clarification,
)
from ..worker.graph_lifecycle import RegisteredCompiledGraph
from .graph import add_test_node, compile_test_graph, new_state_graph

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..thread import CheckpointProjection
    from ..thread.state import TeamState

__all__ = [
    "ClarificationGraph",
    "ParkedClarification",
    "clarification_graph",
    "park_clarification",
    "park_document_approval",
    "park_journaled_permission",
    "park_journaled_permissions",
    "park_permission",
    "park_permissions",
    "park_plan_approval",
]

#: What a provider offers for one tool call: a once-only approval and refusal.
_TOOL_OPTIONS: list[dict[str, Any]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


def _team_state(
    thread_id: str,
    *,
    active_agent: str = "",
    exec_worker: str = "",
    plan_paths: list[str] | None = None,
) -> TeamState:
    """The minimal run state a one-node graph needs to start."""
    state: TeamState = {
        "active_agent": active_agent,
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Park the run.")],
        "next": exec_worker,
        "thread_id": thread_id,
        "active_feature": "agent-panel",
        "token_usage": {},
    }
    if plan_paths is not None:
        state["vault_index"] = {"plan": plan_paths}
    return state


async def _park(
    checkpointer: AsyncSqliteSaver, graph: Any, state: TeamState, thread_id: str
) -> CheckpointProjection:
    """Run *graph* to its interrupts and project the checkpoint it parked at."""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(state, config=config)
    stored = await checkpointer.aget_tuple(config)
    assert stored is not None, "the graph wrote no checkpoint"
    return project_checkpoint_tuple(stored, thread_id=thread_id)


async def _park_request_ids(
    checkpointer: AsyncSqliteSaver, graph: Any, state: TeamState, thread_id: str
) -> list[str]:
    """Run *graph* to its interrupts and return the request ids it parked on."""
    parked = await _park(checkpointer, graph, state, thread_id)
    return [interrupt.interrupt_id for interrupt in parked.pending_interrupts]


def _only(request_ids: list[str]) -> str:
    """The one request a graph parked on."""
    assert len(request_ids) == 1, "the graph did not park on exactly one request"
    return request_ids[0]


def _asking(
    tool_name: str, tool_input: dict[str, Any], offered: list[dict[str, Any]]
) -> Any:
    """A node that asks for one tool call through the worker's own callback."""

    async def ask(state: TeamState) -> dict[str, Any]:
        callback = permission_callback_for(recorded_permission_answers(state))
        await callback(tool_name, tool_input, offered)
        return {}

    return ask


def _permission_graph(
    checkpointer: AsyncSqliteSaver,
    calls: list[tuple[str, dict[str, Any]]],
    offered: list[dict[str, Any]],
) -> Any:
    """A graph whose parallel branches each ask for one of the tool *calls*."""
    builder = new_state_graph()
    for index, (tool_name, tool_input) in enumerate(calls):
        branch = f"ask_{index}"
        add_test_node(builder, branch, _asking(tool_name, tool_input, offered))
        builder.add_edge(START, branch)
        builder.add_edge(branch, END)
    return compile_test_graph(builder, checkpointer=checkpointer)


def _one_call(
    tool_name: str, tool_input: dict[str, Any] | None
) -> list[tuple[str, dict[str, Any]]]:
    """The single tool call a one-permission park asks for."""
    return [(tool_name, {"command": "ls"} if tool_input is None else tool_input)]


async def park_permissions(
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    calls: list[tuple[str, dict[str, Any]]],
    options: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Park *thread_id* on one tool permission per call, all at once, and name them.

    Each call is a parallel branch of the graph, so the run holds every request
    together as a fan-out stage does. *options* defaults to a once-only approval
    and refusal; an empty list parks requests that offer nothing.
    """
    offered = _TOOL_OPTIONS if options is None else options
    graph = _permission_graph(checkpointer, calls, offered)
    return await _park_request_ids(
        checkpointer, graph, _team_state(thread_id), thread_id
    )


async def park_permission(
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    options: list[dict[str, Any]] | None = None,
    tool_name: str = "bash",
    tool_input: dict[str, Any] | None = None,
) -> str:
    """Park *thread_id* on a tool permission offering *options*, and name it."""
    return _only(
        await park_permissions(
            checkpointer,
            thread_id=thread_id,
            calls=_one_call(tool_name, tool_input),
            options=options,
        )
    )


async def park_journaled_permissions(
    checkpointer: AsyncSqliteSaver,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    calls: list[tuple[str, dict[str, Any]]],
    options: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Park *thread_id* on one permission per call, journal each, and name them.

    The run's checkpoint is what makes a request answerable; the journal row is
    the copy the relay writes beside it, carrying the tool the request asked for
    and the *options* the provider offered. Both are parked and journaled as
    :func:`park_permissions` parks them, so *options* defaults the same way.
    """
    offered = _TOOL_OPTIONS if options is None else options
    graph = _permission_graph(checkpointer, calls, offered)
    parked = await _park(checkpointer, graph, _team_state(thread_id), thread_id)
    async with session_factory() as session:
        for interrupt in parked.pending_interrupts:
            tool_name = str(interrupt.payload["tool_name"])
            await record_permission_request(
                session,
                request_id=interrupt.interrupt_id,
                thread_id=thread_id,
                pause_reason_type=tool_name,
                description="Allow action?",
                allowed_options=offered,
                tool_call=tool_name,
            )
        await session.commit()
    return [interrupt.interrupt_id for interrupt in parked.pending_interrupts]


async def park_journaled_permission(
    checkpointer: AsyncSqliteSaver,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    options: list[dict[str, Any]] | None = None,
    tool_name: str = "bash",
    tool_input: dict[str, Any] | None = None,
) -> str:
    """Park *thread_id* on a tool permission offering *options*, journal it, name it."""
    return _only(
        await park_journaled_permissions(
            checkpointer,
            session_factory,
            thread_id=thread_id,
            calls=_one_call(tool_name, tool_input),
            options=options,
        )
    )


async def park_plan_approval(checkpointer: AsyncSqliteSaver, *, thread_id: str) -> str:
    """Park *thread_id* on a plan approval for its exec worker, and name it."""
    builder = new_state_graph()
    add_test_node(builder, "plan_approval", create_plan_approval_node(["coder"]))
    builder.add_edge(START, "plan_approval")
    builder.add_edge("plan_approval", END)
    graph = compile_test_graph(builder, checkpointer=checkpointer)
    state = _team_state(
        thread_id,
        exec_worker="coder",
        plan_paths=[".vault/plan/2026-10-01-agent-panel-plan.md"],
    )
    return _only(await _park_request_ids(checkpointer, graph, state, thread_id))


async def park_document_approval(
    checkpointer: AsyncSqliteSaver, *, thread_id: str, proposal_id: str
) -> str:
    """Park *thread_id* on the research document gate, and name its request.

    A document gate names its request by the proposal it parked on, so the
    submitter hands back *proposal_id* and the gate parks under that id.
    """

    async def submit_proposal(state: TeamState, phase: str) -> str:
        del state, phase
        return proposal_id

    async def finish(state: TeamState) -> dict[str, Any]:
        del state
        return {}

    builder = new_state_graph()
    add_test_node(
        builder,
        "submit",
        create_phase_submit_node(
            "research",
            submit_proposal,
            gate_target="gate",
            revision_target="revise",
            max_revisions=2,
        ),
    )
    add_test_node(
        builder,
        "gate",
        create_phase_gate_node(
            "research", approved_target="approved", revision_target="revise"
        ),
    )
    add_test_node(builder, "approved", finish)
    add_test_node(builder, "revise", finish)
    builder.add_edge(START, "submit")
    builder.add_edge("approved", END)
    builder.add_edge("revise", END)
    graph = compile_test_graph(builder, checkpointer=checkpointer)
    return _only(
        await _park_request_ids(checkpointer, graph, _team_state(thread_id), thread_id)
    )


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
    state = _team_state(thread_id, active_agent="clarification")
    if model_assignment_digest is not None:
        state["model_assignment_digest"] = model_assignment_digest
    if graph_definition_digest is not None:
        state["graph_definition_digest"] = graph_definition_digest
    request = pending_clarification(await _park(checkpointer, graph, state, thread_id))
    assert request is not None, "clarification graph did not park"
    return ParkedClarification(graph=graph, request=request)
