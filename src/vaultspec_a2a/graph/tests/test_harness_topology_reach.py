"""A declared team harness must reach the workers of EVERY topology that has any.

The defect this closes: ``[team.harness] mcp_servers`` was read by exactly one of
the four compilers. The research_adr path forwarded it; the star, pipeline, and
pipeline_loop paths - which all build their workers through the one shared
``_compile_worker_node`` helper - neither accepted nor passed it. The shipped
``vaultspec-doc-editor`` preset is a pipeline that declares ``vaultspec-rag`` and
says in its own comment that the server gives the editor semantic recall of the
document's corpus. It never arrived.

What let it survive is the shape of the coverage, not its absence. A config-level
test asserting ``TeamConfig.effective_harness().mcp_servers == ["vaultspec-rag"]``
passes whether or not the compiler ever reads that value: it proves the
declaration PARSES. So every assertion here is made against the ``session/new``
params a real spawned process received, at the far end of the real compiled
graph - the first point at which "declared" and "delivered" can disagree.

No mocks. The provider factory is a real one by protocol, handing back real
``AcpChatModel`` instances driving the real ACP transport over real subprocesses;
only the agent on the far end of the pipe is a simulator, which is this tree's
established way to ask what the CLI was actually handed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import HumanMessage

from ...team.team_config import (
    TeamHarnessConfig,
    TopologyType,
    load_agent_config,
    load_team_config,
)
from ..compiler import compile_team_graph
from .conftest import deterministic_model_assignment

if TYPE_CHECKING:
    from ...thread.state import TeamState

SIMULATOR_PATH = Path(__file__).parent / "acp_simulator.py"
PYTHON_EXE = sys.executable

#: The server the shipped doc-editor preset declares. Read from the preset in the
#: precondition test below rather than trusted here, so a preset that stops
#: declaring it fails loudly instead of leaving these assertions unsatisfiable.
DECLARED_SERVER = "vaultspec-rag"

#: The shipped preset carrying a real, unedited harness declaration. Its topology
#: is ``pipeline`` - one of the three the compiler used to drop the declaration on.
DOC_EDITOR = "vaultspec-doc-editor"

#: A shipped ``pipeline_loop`` preset. It declares no harness of its own, so the
#: declaration is attached below; what is under test is the TOPOLOGY's compiler,
#: and pipeline_loop needs at least two workers, which the doc-editor has not.
LOOP_PRESET = "mock-autonomous"


class _SessionRecordingProviderFactory:
    """A real provider factory whose models record their own ``session/new``.

    Satisfies ``ProviderFactoryProtocol`` and returns production
    ``AcpChatModel`` instances. The supervisor - identified by the ``None``
    agent_config the compiler passes when a run declares no supervisor persona -
    is given a response that names a worker, because a star run whose supervisor
    says anything else never reaches a worker at all and would leave this test
    asserting on a file that was never written.
    """

    def __init__(
        self, record_dir: Path, workspace_root: Path, supervisor_route: str
    ) -> None:
        self.record_dir = record_dir
        self.workspace_root = workspace_root
        self.supervisor_route = supervisor_route
        self.records: dict[str, Path] = {}

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Path | None = None,
        **kwargs: Any,
    ) -> Any:
        from ...providers.acp_chat_model import AcpChatModel

        agent_id = getattr(agent_config, "id", None)
        response = self.supervisor_route if agent_id is None else "done"
        key = agent_id or "supervisor"
        record = self.record_dir / f"{key}.session-new.json"
        self.records[key] = record
        return AcpChatModel(
            command=[
                PYTHON_EXE,
                str(SIMULATOR_PATH),
                "--response",
                response,
                "--record-session-new",
                str(record),
            ],
            # An armed run always carries its lane token; without it the spawn's
            # config-home isolation does not engage.
            env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},
            workspace_root=str(self.workspace_root),
        )


def _state(thread_id: str) -> TeamState:
    return {
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Revise the document.")],
        "next": "",
        "thread_id": thread_id,
        "token_usage": {},
    }


def _advertised_servers(record: Path) -> list[str]:
    """The MCP server names the spawned CLI was handed on ``session/new``."""
    params = json.loads(record.read_text(encoding="utf-8"))
    return [server["name"] for server in params["mcpServers"]]


async def _drive_until_worker(graph: Any, worker_id: str, thread_id: str) -> None:
    """Stream the compiled graph until *worker_id* has taken its turn.

    Streaming rather than a full ``ainvoke`` because two of the three topologies
    are cyclic: a star's supervisor routes back to itself after every worker turn
    and a pipeline_loop revises until its ceiling, so running either to
    completion would spend subprocess turns proving nothing this test asks
    about. The worker's turn is the whole observation - by the time its update is
    emitted, the session it was handed is on disk.
    """
    async for update in graph.astream(
        _state(thread_id),
        config={"configurable": {"thread_id": thread_id}, "recursion_limit": 12},
    ):
        if worker_id in update:
            return
    raise AssertionError(
        f"the compiled graph completed without {worker_id!r} taking a turn, so "
        "nothing here can be concluded about what its session advertised"
    )


def _compile(team: Any, factory: Any, workspace: Path) -> Any:
    agent_configs = {
        ref.agent_id: load_agent_config(ref.agent_id) for ref in team.workers
    }
    return compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        provider_factory=factory,
        autonomous=True,
        workspace_root=workspace,
        model_assignment=deterministic_model_assignment(team),
    )


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return record_dir, workspace


def test_the_shipped_preset_still_declares_the_server_under_test() -> None:
    """Fixture precondition: the declaration these tests measure delivery of.

    Without it every assertion below is about a server nobody asked for. The
    check is on the SHIPPED preset, unedited, because that preset's declaration
    is the thing the defect discarded.
    """
    harness = load_team_config(DOC_EDITOR).effective_harness()
    assert harness is not None
    assert DECLARED_SERVER in harness.mcp_servers
    assert load_team_config(DOC_EDITOR).topology.type is TopologyType.PIPELINE


@pytest.mark.asyncio
async def test_the_shipped_doc_editor_pipeline_delivers_its_declared_server(
    tmp_path: Path,
) -> None:
    """The acceptance case, on the shipped preset with nothing edited.

    The preset is loaded as it ships, compiled by the production compiler, and
    driven for real; the assertion is that the session its worker was handed
    advertises the server the preset declares. This is the claim the config-level
    coverage could not make, and the one that was false.
    """
    record_dir, workspace = _dirs(tmp_path)
    team = load_team_config(DOC_EDITOR)
    worker_id = team.workers[0].agent_id
    factory = _SessionRecordingProviderFactory(record_dir, workspace, worker_id)

    graph = _compile(team, factory, workspace)
    await _drive_until_worker(graph, worker_id, "harness-pipeline")

    assert DECLARED_SERVER in _advertised_servers(factory.records[worker_id]), (
        f"the shipped {DOC_EDITOR!r} preset declares {DECLARED_SERVER!r} and its "
        "compiled worker was handed a session without it"
    )


@pytest.mark.asyncio
async def test_the_star_compiler_delivers_a_declared_server(tmp_path: Path) -> None:
    """Same preset, same declaration, star topology.

    Only ``topology.type`` differs from the case above, which is precisely the
    axis the defect ran along: the declaration and the worker are identical, so a
    difference in outcome could only come from which compiler ran. Reaching the
    compiler through ``model_copy`` is the documented route a config takes when
    it has already passed its validators.
    """
    record_dir, workspace = _dirs(tmp_path)
    base = load_team_config(DOC_EDITOR)
    team = base.model_copy(
        update={
            "topology": base.topology.model_copy(update={"type": TopologyType.STAR})
        }
    )
    worker_id = team.workers[0].agent_id
    factory = _SessionRecordingProviderFactory(record_dir, workspace, worker_id)

    graph = _compile(team, factory, workspace)
    await _drive_until_worker(graph, worker_id, "harness-star")

    assert DECLARED_SERVER in _advertised_servers(factory.records[worker_id])


@pytest.mark.asyncio
async def test_the_pipeline_loop_compiler_delivers_a_declared_server(
    tmp_path: Path,
) -> None:
    """A shipped pipeline_loop preset, given the same declaration.

    pipeline_loop refuses a single-worker team as a degenerate self-loop, so this
    uses the shipped multi-worker loop preset and attaches the harness rather
    than reshaping the doc-editor into something the topology would reject. The
    first stage of the chain is the observation point: it is a plain worker built
    by the shared helper, reached before any loop wrapping.
    """
    record_dir, workspace = _dirs(tmp_path)
    base = load_team_config(LOOP_PRESET)
    assert base.topology.type is TopologyType.PIPELINE_LOOP
    team = base.model_copy(
        update={"harness": TeamHarnessConfig(mcp_servers=[DECLARED_SERVER])}
    )
    worker_id = team.topology.order[0]
    factory = _SessionRecordingProviderFactory(record_dir, workspace, worker_id)

    graph = _compile(team, factory, workspace)
    await _drive_until_worker(graph, worker_id, "harness-loop")

    assert DECLARED_SERVER in _advertised_servers(factory.records[worker_id])


@pytest.mark.asyncio
async def test_a_preset_that_declares_no_server_is_handed_none(
    tmp_path: Path,
) -> None:
    """The contrast that makes the three cases above mean something.

    A fix that composed the rag server onto every worker unconditionally would
    satisfy all three admissions and be a different, worse defect. Here the same
    shipped preset has its declaration emptied - everything else identical - and
    the worker's session must carry no injected server at all. What the compiler
    forwards is the DECLARATION, not a default.
    """
    record_dir, workspace = _dirs(tmp_path)
    base = load_team_config(DOC_EDITOR)
    harness = base.effective_harness()
    assert harness is not None
    team = base.model_copy(
        update={"harness": harness.model_copy(update={"mcp_servers": []})}
    )
    worker_id = team.workers[0].agent_id
    factory = _SessionRecordingProviderFactory(record_dir, workspace, worker_id)

    graph = _compile(team, factory, workspace)
    await _drive_until_worker(graph, worker_id, "harness-undeclared")

    assert _advertised_servers(factory.records[worker_id]) == []
