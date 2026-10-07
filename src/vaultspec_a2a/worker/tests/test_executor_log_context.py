"""Every record a dispatch logs names the run and dispatch it belongs to.

A real executor runs a real graph through a real relay while the package's
loggers write through the production correlation filter; each record captured
during the dispatch must carry the dispatch's identity, whichever module logged
it and whether or not that call site passed it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, override

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...providers.team_selection import model_assignment_digest
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...utils.logging import LogContextFilter
from ..executor import Executor
from .test_executor import _current_ingest_dispatch, _make_recording_bridge


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self.addFilter(LogContextFilter())

    @override
    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio(loop_scope="function")
async def test_every_record_of_a_dispatch_carries_its_identity() -> None:
    async def step(state: Any) -> dict[str, Any]:
        del state
        logging.getLogger("vaultspec_a2a.graph.test_step").info("node ran")
        return {"messages": [AIMessage(content="done")]}

    capture = _Capture()
    package = logging.getLogger("vaultspec_a2a")
    previous_level = package.level
    package.addHandler(capture)
    package.setLevel(logging.DEBUG)
    try:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
            await checkpointer.setup()
            relayed: list[dict[str, Any]] = []
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            try:
                request = _current_ingest_dispatch("log-context-run")
                builder = new_state_graph()
                add_test_node(builder, "step", step)
                builder.add_edge("__start__", "step")
                builder.add_edge("step", "__end__")
                definition = request.require_graph_definition()
                executor.register_compiled_graph(
                    request.thread_id,
                    (
                        definition.team_id,
                        request.workspace_root,
                        request.autonomous,
                        model_assignment_digest(request.model_assignment),
                        definition.digest(),
                    ),
                    compile_test_graph(builder, checkpointer=checkpointer),
                )
                capture.records.clear()
                await asyncio.wait_for(executor.handle_dispatch(request), timeout=10.0)
                during = list(capture.records)
            finally:
                await bridge.close()
                await executor.shutdown()
    finally:
        package.removeHandler(capture)
        package.setLevel(previous_level)

    assert any(r.getMessage() == "node ran" for r in during)
    for record in during:
        assert getattr(record, "dispatch_id", None) == request.dispatch_id, (
            record.name,
            record.getMessage(),
        )
        assert getattr(record, "thread_id", None) == request.thread_id
