"""LangGraph orchestration engine for agent teams."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from .nodes.supervisor import create_supervisor_node
from .nodes.worker import create_worker_node
from .state import TeamState


def compile_team_graph(
    supervisor_model: BaseChatModel,
    worker_models: dict[str, BaseChatModel],
    checkpointer: AsyncSqliteSaver | None = None,
) -> Any:  # noqa: ANN401
    """Compile the LangGraph orchestration engine with dynamic workers.

    Args:
        supervisor_model: The LLM used for routing tasks.
        worker_models: A dict mapping worker names to their specific LLMs.
        checkpointer: An optional SQLite checkpointer for state persistence.

    Returns:
        The compiled StateGraph runnable.
    """
    builder = StateGraph(TeamState)

    workers = list(worker_models.keys())

    # 1. Add Supervisor
    supervisor_prompt = (
        "You are a supervisor managing a team of expert assistants. "
        f"Your active team members are: {', '.join(workers)}. "
        "Review the recent messages, identify what needs to be done, "
        "and decide who should act next to progress the goal."
    )
    supervisor_node = create_supervisor_node(
        model=supervisor_model,
        system_prompt=supervisor_prompt,
        workers=workers,
    )
    builder.add_node("supervisor", supervisor_node)

    # 2. Add Workers
    for worker_name, model in worker_models.items():
        # We enforce a single static prompt for all workers for now
        # as per the pipeline topology ADR
        worker_sys_prompt = "You are a helpful expert assistant."
        worker_node = create_worker_node(model, worker_sys_prompt, name=worker_name)
        builder.add_node(worker_name, worker_node)
        # Workers always report back to the supervisor
        builder.add_edge(worker_name, "supervisor")

    # 3. Routing Edges
    builder.add_edge(START, "supervisor")

    # Conditional edge from supervisor based on the 'next' state key
    route_map = {name: name for name in workers}
    route_map["FINISH"] = END

    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["next"],
        route_map,
    )

    return builder.compile(checkpointer=checkpointer)
