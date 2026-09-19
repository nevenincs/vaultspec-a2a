"""Accepted compiler inputs survive configuration edits and reject partial state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from ...control.execution_authority import resolve_execution_authority
from ...control.tests._catalog_authority import current_execution_metadata
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ..executor import Executor
from ..graph_lifecycle import GraphCompilationError
from .test_executor import _make_bridge

if TYPE_CHECKING:
    from pathlib import Path


def _definition(tmp_path: Path) -> FrozenGraphDefinition:
    return freeze_graph_definition(
        load_team_config("mock-success-single", workspace_root=tmp_path),
        workspace_root=tmp_path,
    )


@pytest.mark.parametrize("damage", ["missing_field", "no_timeout", "missing_agent"])
def test_partial_executable_authority_is_refused(tmp_path: Path, damage: str) -> None:
    raw = _definition(tmp_path).model_dump(mode="json")
    if damage == "missing_field":
        del raw["team"]["graph"]["recursion_limit"]
    elif damage == "no_timeout":
        raw["team"]["graph"]["step_timeout_seconds"] = None
    else:
        raw["agents"].clear()
    with pytest.raises(ValidationError):
        FrozenGraphDefinition.model_validate(raw)


@pytest.mark.asyncio
async def test_worker_compiles_accepted_program_after_files_change(
    tmp_path: Path,
) -> None:
    definition = _definition(tmp_path)
    request = DispatchRequest(
        action="ingest",
        thread_id="frozen-run",
        workspace_root=str(tmp_path),
        team_preset=definition.team_id,
        graph_definition=definition,
        recursion_limit=17,
        model_assignment=resolve_execution_authority(
            current_execution_metadata(tmp_path, required_roles=("mock-coder-success",))
        ).model_assignment,
    )
    for kind, name in (
        ("teams", "mock-success-single"),
        ("agents", "mock-coder-success"),
    ):
        path = tmp_path / ".vaultspec" / kind / f"{name}.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid toml [", encoding="utf-8")
    bridge = _make_bridge()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.db")) as saver:
        executor = Executor(saver, bridge)
        try:
            graph = await executor._graph_lifecycle.get_or_compile_graph(request)
            assert graph is not None
            assert cast("Any", graph).step_timeout == 60
            changed = definition.model_dump(mode="json")
            changed["team"]["graph"]["step_timeout_seconds"] = 61
            replacement = FrozenGraphDefinition.model_validate(changed)
            with pytest.raises(GraphCompilationError, match="bound run"):
                await executor._graph_lifecycle.get_or_compile_graph(
                    request.model_copy(update={"graph_definition": replacement})
                )
        finally:
            await executor.shutdown()
            await bridge.close()
