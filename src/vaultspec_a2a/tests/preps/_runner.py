"""Shared runner infrastructure for preps/ scenarios."""

from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph

from ...graph.compiler import compile_team_graph
from ...team.team_config import load_agent_config, load_team_config
from ...thread.errors import AgentConfigNotFoundError


@asynccontextmanager
async def setup_graph(
    team_id: str,
    *,
    autonomous: bool = False,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
) -> AsyncIterator[CompiledStateGraph]:
    """Load team+agent configs, create temp-file checkpointer, compile graph.

    Yields the compiled graph. Checkpointer is alive for the duration of the
    context manager.
    """
    team_config = load_team_config(team_id)
    agent_configs = {
        w.agent_id: load_agent_config(w.agent_id) for w in team_config.workers
    }

    supervisor_agent_config = None
    if team_config.topology.type in ("star", "pipeline_loop"):
        with suppress(AgentConfigNotFoundError):
            supervisor_agent_config = load_agent_config("vaultspec-supervisor")

    # Temp-file checkpointer (not :memory: — allows post-mortem inspection)
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    async with AsyncSqliteSaver.from_conn_string(tmp_path) as checkpointer:
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
        yield graph


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
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    input_state = {"messages": [HumanMessage(content=user_message)]}
    mode = stream_mode or ["updates"]

    async for chunk in graph.astream(input_state, config, stream_mode=mode):  # type: ignore[call-overload]
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
        print(
            f"\nLangSmith trace: check project '{project}' at https://smith.langchain.com"
        )
    else:
        print("\nLangSmith tracing disabled. Set LANGSMITH_TRACING=true to enable.")
