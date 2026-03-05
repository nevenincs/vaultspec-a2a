"""Shared runner infrastructure for preps/ scenarios."""

import os
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph

from lib.core import compile_team_graph, load_agent_config, load_team_config


async def setup_graph(
    team_id: str,
    *,
    autonomous: bool = False,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
) -> tuple[CompiledStateGraph, AsyncSqliteSaver]:
    """Load team+agent configs, create temp-file checkpointer, compile graph.

    Returns (compiled_graph, checkpointer) — caller must close checkpointer.
    """
    team_config = load_team_config(team_id)
    agent_configs = {
        w.agent_id: load_agent_config(w.agent_id)
        for w in team_config.workers
    }

    supervisor_agent_config = None
    if team_config.supervisor and team_config.supervisor.agent_id:
        supervisor_agent_config = load_agent_config(team_config.supervisor.agent_id)

    # Temp-file checkpointer (not :memory: — allows post-mortem inspection)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    checkpointer = AsyncSqliteSaver.from_conn_string(tmp.name)
    await checkpointer.setup()

    graph = compile_team_graph(
        team_config=team_config,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_agent_config,
        workspace_root=workspace_root,
        autonomous=autonomous,
        feature_tag=feature_tag,
    )
    return graph, checkpointer


async def run_scenario(
    graph: CompiledStateGraph,
    user_message: str,
    *,
    thread_id: str = "preps-001",
    stream_mode: list[str] | None = None,
) -> None:
    """Stream graph execution and print events to stdout.

    Uses stream_mode=["updates"] by default. Prints each node update.
    """
    config = {"configurable": {"thread_id": thread_id}}
    input_state = {"messages": [HumanMessage(content=user_message)]}
    mode = stream_mode or ["updates"]

    async for chunk in graph.astream(input_state, config, stream_mode=mode):
        if isinstance(chunk, tuple):
            mode_name, data = chunk
            print(f"\n{'=' * 60}")
            print(f"[{mode_name}]")
            _print_data(data)
        else:
            print(f"\n{'=' * 60}")
            _print_data(chunk)


def _print_data(data: Any) -> None:
    """Pretty-print a stream event."""
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"  {key}: {_summarize(value)}")
    else:
        print(f"  {data}")


def _summarize(value: Any, max_len: int = 200) -> str:
    """Summarize a value for console output."""
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "..."


def print_trace_url(thread_id: str = "preps-001") -> None:
    """Print LangSmith trace URL hint."""
    project = os.environ.get("LANGSMITH_PROJECT", "default")
    if os.environ.get("LANGSMITH_TRACING", "").lower() == "true":
        print(f"\nLangSmith trace: check project '{project}' at https://smith.langchain.com")
    else:
        print("\nLangSmith tracing disabled. Set LANGSMITH_TRACING=true to enable.")
