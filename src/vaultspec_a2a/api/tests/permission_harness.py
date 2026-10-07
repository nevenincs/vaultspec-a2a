"""Shared real-behavior harness for permission respond tests.

The respond verb reads what a run is parked on from the run's checkpoint, so a
test that answers a request has to park a run on it first. These helpers park a
real graph over a real checkpointer on the real interrupts the verb answers: a
tool permission raised by the worker's own permission callback, a plan
approval raised by the supervisor's own approval node, and a document approval
raised by a phase gate. The request id is the one its producer named it, read
back from the checkpoint rather than chosen by the test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START

from ...graph.nodes._worker_permissions import (
    permission_callback_for,
    recorded_permission_answers,
)
from ...graph.nodes.phase_gate import create_phase_gate_node, create_phase_submit_node
from ...graph.nodes.supervisor import create_plan_approval_node
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...thread import project_checkpoint_tuple

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ...thread.state import TeamState

__all__ = [
    "TOOL_OPTIONS",
    "park_document_approval",
    "park_permission",
    "park_permissions",
    "park_plan_approval",
]

#: What a provider offers for one tool call: a once-only approval and refusal.
TOOL_OPTIONS: list[dict[str, Any]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


def _team_state(
    thread_id: str, *, exec_worker: str = "", plan_paths: list[str] | None = None
) -> TeamState:
    """The minimal run state a one-node graph needs to start."""
    state: TeamState = {
        "active_agent": "",
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
) -> list[str]:
    """Run *graph* to its interrupts and return the request ids it parked on."""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(state, config=config)
    stored = await checkpointer.aget_tuple(config)
    assert stored is not None, "the graph wrote no checkpoint"
    parked = project_checkpoint_tuple(stored, thread_id=thread_id).pending_interrupts
    return [interrupt.interrupt_id for interrupt in parked]


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


async def park_permissions(
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    calls: list[tuple[str, dict[str, Any]]],
    options: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Park *thread_id* on one tool permission per call, all at once, and name them.

    Each call is a parallel branch of the graph, so the run holds every request
    together as a fan-out stage does. *options* defaults to :data:`TOOL_OPTIONS`;
    an empty list parks requests that offer nothing.
    """
    offered = TOOL_OPTIONS if options is None else options
    builder = new_state_graph()
    for index, (tool_name, tool_input) in enumerate(calls):
        branch = f"ask_{index}"
        add_test_node(builder, branch, _asking(tool_name, tool_input, offered))
        builder.add_edge(START, branch)
        builder.add_edge(branch, END)
    graph = compile_test_graph(builder, checkpointer=checkpointer)
    return await _park(checkpointer, graph, _team_state(thread_id), thread_id)


async def park_permission(
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    options: list[dict[str, Any]] | None = None,
    tool_name: str = "bash",
    tool_input: dict[str, Any] | None = None,
) -> str:
    """Park *thread_id* on a tool permission offering *options*, and name it."""
    call_input = {"command": "ls"} if tool_input is None else tool_input
    return _only(
        await park_permissions(
            checkpointer,
            thread_id=thread_id,
            calls=[(tool_name, call_input)],
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
    return _only(await _park(checkpointer, graph, state, thread_id))


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
    return _only(await _park(checkpointer, graph, _team_state(thread_id), thread_id))
