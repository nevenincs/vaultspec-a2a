"""The active project is minted once and named in one spelling everywhere.

A run's project is minted once, not re-derived at every boundary it crosses. If
admission dispatched its locally resolved spelling while the durable record
kept the caller's original, every later dispatch - follow-up, clarification
response, verdict resume, crash recovery - would read the durable one back: two
strings for one directory, agreeing only by coincidence. The worker's graph
cache is keyed on the raw string, so a single workspace would then occupy two
entries and recompile its graph on the first follow-up.

These tests drive the real seams that produced the split: the admission
function, the dispatch schema every construction site validates through, and
the worker's own cache-key former and registration seam.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast, override

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from ...context.metadata import ThreadMetadata
from ...control._thread_metadata import dispatchable_workspace_root
from ...database import normalize_workspace_identity
from ...ipc.schemas import DispatchRequest, canonical_project_root
from ...providers.team_selection import FrozenLaneAssignment, model_assignment_digest
from ...streaming import RunEventProducer
from ...team.team_config import load_team_config
from ...testing import (
    DEFAULT_TEAM_PRESET,
    add_test_node,
    compile_test_graph,
    deterministic_model_assignment,
    new_state_graph,
    settings_override,
    stand_in_definition_digest,
)
from ...thread.errors import ConfigError
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ...thread.state import TeamState
from ...worker.catalog_store import RunCatalogStore
from ...worker.graph_lifecycle import (
    GraphCompilationError,
    GraphLifecycleManager,
    RegisteredCompiledGraph,
    graph_cache_key,
)
from ...worker.ipc import WorkerBridge
from ...worker.token_store import RunTokenStore
from ..thread_service import process_metadata

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def _uncanonical_spelling(workspace: Path) -> str:
    """Return a second, equally valid spelling of *workspace*.

    A detour through a sibling directory plus POSIX separators reproduces, with
    no symlink privileges and on either platform, exactly the shape the split
    took: the same directory written two ways.
    """
    return str(workspace.parent / "sibling" / ".." / workspace.name).replace("\\", "/")


def _assignment(model_name: str) -> dict[str, FrozenLaneAssignment]:
    """The preset's deterministic assignment, frozen under *model_name*.

    The model name is the one field varied, so two assignments built under
    different names differ in identity and in nothing else.
    """
    team = load_team_config(DEFAULT_TEAM_PRESET)
    return {
        role: lane.model_copy(update={"model_name": model_name})
        for role, lane in deterministic_model_assignment(team).items()
    }


def _definition(workspace: Path) -> FrozenGraphDefinition:
    return freeze_graph_definition(
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=workspace),
        workspace_root=workspace,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A real existing project directory with a real sibling to detour through."""
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "sibling").mkdir()
    return root


class TestStoredMetadataOnlyYieldsADispatchableProject:
    """The two resume paths refuse a stored root the dispatch boundary rejects.

    A verdict resume and a clarification answer both read the stored project out
    of thread metadata and hand it to a dispatch. Both construct that dispatch
    AFTER claiming a control action, so a value the request constructor refuses
    does not fail cleanly - it leaves the run holding a claim with no dispatch.
    The reader therefore answers with what the boundary would accept, and the
    unusable cases all become "resume without re-siting".
    """

    @staticmethod
    def _metadata(root: object) -> str:
        return json.dumps({"workspace_root": root})

    @pytest.mark.parametrize(
        ("label", "stored"),
        [
            ("relative", "workspaces/project"),
            ("blank", ""),
            ("whitespace", "   "),
            ("wrong type", 17),
            ("absent", None),
        ],
    )
    def test_a_root_the_dispatch_would_refuse_reads_as_no_project(
        self, label: str, stored: object
    ) -> None:
        """Each of these once flowed through and raised at the request."""
        assert dispatchable_workspace_root(self._metadata(stored)) is None, label

    @pytest.mark.parametrize(
        "metadata", [None, "", "not json at all", "[]", '"a string"', "null"]
    )
    def test_unusable_metadata_reads_as_no_project(self, metadata: str | None) -> None:
        """Undecodable and non-object metadata are the same answer, never a raise."""
        assert dispatchable_workspace_root(metadata) is None

    def test_a_real_root_survives_and_arrives_minted(self, workspace: Path) -> None:
        """The usable case still works, and lands in the one canonical spelling."""
        stored = _uncanonical_spelling(workspace)
        assert stored != str(workspace)

        resolved = dispatchable_workspace_root(self._metadata(stored))

        assert resolved == canonical_project_root(stored)
        assert resolved == str(workspace)

    def test_every_refused_value_would_have_raised_at_the_dispatch(self) -> None:
        """The reason the reader refuses, asserted rather than described.

        Without this, the parametrised refusals above would be consistent with a
        reader that is merely fussy. These are the values that actually break the
        request the caller goes on to build.
        """
        for stored in ("workspaces/project", "", "   "):
            with pytest.raises(ValidationError):
                DispatchRequest(
                    action="resume",
                    thread_id="run-1",
                    workspace_root=stored,
                    recursion_limit=25,
                )


class TestAdmissionMintsOnce:
    """Admission is where the run's project spelling is decided."""

    def test_admission_returns_the_canonical_spelling(self, workspace: Path) -> None:
        raw = _uncanonical_spelling(workspace)
        assert raw != str(workspace)

        minted, _nickname, _metadata_json = process_metadata(
            ThreadMetadata(workspace_root=raw), "run-1", None
        )

        assert str(minted) == canonical_project_root(workspace)

    def test_the_durable_record_carries_the_minted_spelling(
        self, workspace: Path
    ) -> None:
        """The record every later dispatch reads back must hold the mint.

        Serialising the caller's original spelling is what let a follow-up name
        the project differently from the run that started it.
        """
        raw = _uncanonical_spelling(workspace)

        minted, _nickname, metadata_json = process_metadata(
            ThreadMetadata(workspace_root=raw), "run-1", None
        )

        assert json.loads(metadata_json)["workspace_root"] == str(minted)

    def test_the_mint_preserves_the_durable_discovery_selector(
        self, workspace: Path
    ) -> None:
        """Storage keeps selecting existing rows; the mint is not a re-hash.

        Workspace-scoped run discovery hashes a case-folded symlink resolution
        of the stored root. Storing the minted spelling instead of the caller's
        must leave that hash untouched, or discovery would silently stop
        matching every row written before this change.
        """
        raw = _uncanonical_spelling(workspace)

        _minted, _nickname, metadata_json = process_metadata(
            ThreadMetadata(workspace_root=raw), "run-1", None
        )
        stored = json.loads(metadata_json)["workspace_root"]

        assert normalize_workspace_identity(stored) == normalize_workspace_identity(raw)

    def test_a_missing_project_directory_is_still_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not an existing directory"):
            process_metadata(
                ThreadMetadata(workspace_root=str(tmp_path / "absent")), "run-1", None
            )

    def test_managed_unarmed_profile_refuses_foreign_project(
        self, tmp_path: Path
    ) -> None:
        managed = tmp_path / "managed"
        foreign = tmp_path / "foreign"
        managed.mkdir()
        foreign.mkdir()

        with (
            settings_override(desktop_app_home=None, workspace_root=managed),
            pytest.raises(ValueError, match="configured workspace root"),
        ):
            process_metadata(ThreadMetadata(workspace_root=str(foreign)), "run-1", None)

    def test_managed_unarmed_profile_accepts_configured_root_descendant(
        self, tmp_path: Path
    ) -> None:
        managed = tmp_path / "managed"
        project = managed / "project"
        project.mkdir(parents=True)

        with settings_override(desktop_app_home=None, workspace_root=managed):
            admitted, _nickname, _metadata_json = process_metadata(
                ThreadMetadata(workspace_root=str(project)), "run-1", None
            )

        assert admitted == project.resolve()


class TestDispatchCarriesTheMintedProject:
    """The wire mints, so no construction site can dispatch a raw path."""

    def test_two_spellings_reach_the_worker_as_one(self, workspace: Path) -> None:
        """The run-start and follow-up shapes must agree.

        Run start dispatches the path admission resolved; a follow-up dispatches
        the string it reads out of the durable record - which, for a run created
        before the mint existed, is still the caller's original spelling. Both
        shapes are built here the way their production callers build them.
        """
        legacy_stored = _uncanonical_spelling(workspace)
        started, _nickname, _metadata_json = process_metadata(
            ThreadMetadata(workspace_root=legacy_stored), "run-1", None
        )

        run_start = DispatchRequest(
            action="ingest",
            thread_id="run-1",
            team_preset="preset",
            workspace_root=str(started),
            recursion_limit=25,
        )
        follow_up = DispatchRequest(
            action="ingest",
            thread_id="run-1",
            team_preset="preset",
            workspace_root=legacy_stored,
            recursion_limit=25,
        )

        assert run_start.workspace_root == follow_up.workspace_root

    def test_the_minted_project_survives_the_dispatch_wire(
        self, workspace: Path
    ) -> None:
        """Gateway and worker are separate processes; the value crosses as JSON."""
        sent = DispatchRequest(
            action="ingest",
            thread_id="run-1",
            workspace_root=_uncanonical_spelling(workspace),
            recursion_limit=25,
        )

        received = DispatchRequest.model_validate(sent.model_dump())

        assert received.workspace_root == sent.workspace_root
        assert received.workspace_root == canonical_project_root(workspace)

    def test_an_ingest_without_a_project_is_a_protocol_error(self) -> None:
        with pytest.raises(ValidationError, match="must name the run's active project"):
            DispatchRequest(action="ingest", thread_id="run-1", recursion_limit=25)

    @pytest.mark.parametrize("action", ["resume", "cancel"])
    def test_resume_and_cancel_stay_tolerant(self, action: str) -> None:
        """A resume rejoins a graph that holds the project; a cancel names none."""
        dispatch = DispatchRequest.model_validate(
            {"action": action, "thread_id": "run-1", "recursion_limit": 25}
        )

        assert dispatch.workspace_root is None

    @pytest.mark.parametrize("spelling", ["", "   ", "relative/path", "./here"])
    def test_a_project_that_would_resolve_against_the_server_is_refused(
        self, spelling: str
    ) -> None:
        """Blank and relative spellings resolve into the serving process's tree.

        That is the failure the admission gate exists to prevent, so the wire
        refuses them rather than quietly siting the run in a2a's own directory.
        """
        with pytest.raises(ValidationError):
            DispatchRequest(
                action="resume",
                thread_id="run-1",
                workspace_root=spelling,
                recursion_limit=25,
            )


class TestGraphStateNamesTheProject:
    """``TeamState.workspace_root`` must be written, not merely declared.

    The state key has always documented itself as threaded in through graph
    input. Nothing wrote it, so both readers - the worker node and the research
    node in the compiler - fell through to their compile-time closure on every
    turn and the declaration was dead capability.
    """

    @staticmethod
    def _ingest(workspace: Path, *, content: str) -> DispatchRequest:
        return DispatchRequest(
            action="ingest",
            thread_id="run-1",
            team_preset=DEFAULT_TEAM_PRESET,
            workspace_root=_uncanonical_spelling(workspace),
            content=content,
            recursion_limit=25,
            graph_definition=_definition(workspace),
        )

    def test_the_first_turn_carries_the_minted_project(self, workspace: Path) -> None:
        graph_input = GraphLifecycleManager.build_graph_input(
            self._ingest(workspace, content="build it"), is_first_ingest=True
        )

        assert graph_input["workspace_root"] == canonical_project_root(workspace)

    def test_a_follow_up_turn_carries_it_too(self, workspace: Path) -> None:
        """Not first-ingest-only: a checkpoint predating the key must be repaired.

        The key carries no reducer, and the graph is cached per project, so the
        value cannot drift within a thread - writing it every turn is a
        last-write-wins no-op on a fresh checkpoint and a repair on an old one.
        """
        graph_input = GraphLifecycleManager.build_graph_input(
            self._ingest(workspace, content="and again"), is_first_ingest=False
        )

        assert graph_input["workspace_root"] == canonical_project_root(workspace)

    def test_the_state_key_the_graph_declares_is_the_one_written(
        self, workspace: Path
    ) -> None:
        """Guard the contract against a rename on either side of the seam."""
        graph_input = GraphLifecycleManager.build_graph_input(
            self._ingest(workspace, content="build it"), is_first_ingest=True
        )

        assert "workspace_root" in TeamState.__annotations__
        assert set(graph_input) <= set(TeamState.__annotations__)

    @pytest.mark.asyncio
    async def test_a_running_node_reads_the_project_off_state(
        self, workspace: Path
    ) -> None:
        """The dict is not the contract; what a node sees is.

        LangGraph validates graph input against ``TeamState``, so a key the
        schema does not carry would never reach a node. Driving a real compiled
        graph is the only thing that proves the seam end to end.
        """
        seen: dict[str, object] = {}

        def observe(state: dict[str, object]) -> dict[str, object]:
            seen["workspace_root"] = state.get("workspace_root")
            return {}

        builder = new_state_graph()
        add_test_node(builder, "observe", observe)
        builder.add_edge("__start__", "observe")
        builder.add_edge("observe", "__end__")
        graph = compile_test_graph(builder, checkpointer=InMemorySaver())

        await graph.ainvoke(
            GraphLifecycleManager.build_graph_input(
                self._ingest(workspace, content="build it"), is_first_ingest=True
            ),
            {"configurable": {"thread_id": "run-1"}},
        )

        assert seen["workspace_root"] == canonical_project_root(workspace)

    def test_a_follow_up_still_omits_the_reducer_backed_fields(
        self, workspace: Path
    ) -> None:
        """Adding a key to the shared dict must not leak the first-ingest set.

        ``current_plan=[]`` on a follow-up trips the replace-plan reducer's clear
        sentinel and wipes the supervisor's plan, so the omission is load-bearing.
        """
        graph_input = GraphLifecycleManager.build_graph_input(
            self._ingest(workspace, content="and again"), is_first_ingest=False
        )

        assert "current_plan" not in graph_input
        assert "artifacts" not in graph_input
        assert "token_usage" not in graph_input
        assert "active_agent" not in graph_input


class TestAuthoringSubmitterIsBoundToTheProject:
    """The run's authoring submitter is built on its own project."""

    @pytest.mark.asyncio
    async def test_a_document_run_without_a_project_refuses_to_build_one(self) -> None:
        """Fail closed rather than open a session under no project.

        The submitter's scope is what the engine authorises each authoring
        command against. With no project it would fall back to whichever
        workspace the engine holds active at command time - the drift the
        run-bound scope exists to remove - so construction refuses instead.
        """
        manager = GraphLifecycleManager(
            checkpointer=InMemorySaver(),
            bridge=WorkerBridge(api_url="http://127.0.0.1:1", worker_id="identity"),
            producer=RunEventProducer(),
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )

        with pytest.raises(ConfigError, match="must name the project it authors into"):
            await manager._build_proposal_submitter(None)


class TestOneWorkspaceOneGraphEntry:
    """A run's graph cache entry is keyed on its canonical workspace.

    Each run compiles its own graph (a compiled graph holds model instances a
    provider refuses to share between concurrent turns); within a run, every
    spelling of its project reaches that one entry.
    """

    @staticmethod
    def _manager() -> GraphLifecycleManager:
        return GraphLifecycleManager(
            checkpointer=InMemorySaver(),
            bridge=WorkerBridge(api_url="http://127.0.0.1:1", worker_id="identity"),
            producer=RunEventProducer(),
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )

    @staticmethod
    def _graph() -> RegisteredCompiledGraph:
        def finish_node(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        builder = new_state_graph()
        add_test_node(builder, "finish", finish_node)
        builder.add_edge("__start__", "finish")
        builder.add_edge("finish", "__end__")
        return compile_test_graph(builder, checkpointer=InMemorySaver())

    def test_two_spellings_key_the_same_entry(self, workspace: Path) -> None:
        digest = model_assignment_digest({})
        definition_digest = _definition(workspace).digest()
        assert graph_cache_key(
            ("preset", str(workspace), False, digest, definition_digest),
            thread_id="r",
        ) == graph_cache_key(
            (
                "preset",
                _uncanonical_spelling(workspace),
                False,
                digest,
                definition_digest,
            ),
            thread_id="r",
        )

    def test_a_project_less_key_is_still_a_key(self) -> None:
        """A run with no project still keys, so the mint cannot break cancel."""
        digest = model_assignment_digest({})
        definition_digest = stand_in_definition_digest("preset")
        assert graph_cache_key(
            ("preset", None, True, digest, definition_digest), thread_id="r"
        ) == ("preset", None, True, digest, definition_digest, "r")

    def test_model_assignment_identity_partitions_the_graph_cache(self) -> None:
        first = model_assignment_digest(_assignment("first"))
        same = model_assignment_digest(_assignment("first"))
        other = model_assignment_digest(_assignment("second"))
        definition_digest = stand_in_definition_digest("preset")

        assert graph_cache_key(
            ("preset", None, False, first, definition_digest), thread_id="r"
        ) == graph_cache_key(
            ("preset", None, False, same, definition_digest), thread_id="r"
        )
        assert graph_cache_key(
            ("preset", None, False, first, definition_digest), thread_id="r"
        ) != graph_cache_key(
            ("preset", None, False, other, definition_digest), thread_id="r"
        )

    def test_two_runs_never_share_a_graph_entry(self) -> None:
        digest = model_assignment_digest({})
        definition_digest = stand_in_definition_digest("preset")
        assert graph_cache_key(
            ("preset", None, False, digest, definition_digest), thread_id="run-1"
        ) != graph_cache_key(
            ("preset", None, False, digest, definition_digest), thread_id="run-2"
        )

    def test_two_runs_on_one_workspace_hold_their_own_entries(
        self, workspace: Path
    ) -> None:
        """Two runs of one preset never share a graph, but agree on the project.

        A compiled graph holds its nodes' model instances, and a provider model
        refuses concurrent use, so a second run's overlapping turn on a shared
        graph failed. Each run keeps its own entry; both still record the one
        canonical spelling of the project, whichever spelling registered them.
        """
        manager = self._manager()

        definition_digest = stand_in_definition_digest("preset")
        for thread_id, spelling in (
            ("run-1", str(workspace)),
            ("run-2", _uncanonical_spelling(workspace)),
        ):
            manager.register_compiled_graph(
                thread_id,
                (
                    DEFAULT_TEAM_PRESET,
                    spelling,
                    False,
                    model_assignment_digest(_assignment("current")),
                    definition_digest,
                ),
                self._graph(),
            )

        assert manager.graph_count == 2
        first = manager.cache_key_for_thread("run-1")
        second = manager.cache_key_for_thread("run-2")
        assert first is not None and second is not None
        assert first[:5] == second[:5]
        assert first != second

    @pytest.mark.asyncio
    async def test_a_dispatch_reuses_the_registered_graph(
        self, workspace: Path
    ) -> None:
        """The real lookup path, driven by a real dispatch, must hit the entry.

        Registration and lookup are separate seams; proving the key former
        collapses spellings says nothing unless the dispatch path forms its key
        the same way.
        """
        manager = self._manager()
        graph = self._graph()
        manager.register_compiled_graph(
            "run-1",
            (
                DEFAULT_TEAM_PRESET,
                str(workspace),
                False,
                model_assignment_digest(_assignment("current")),
                _definition(workspace).digest(),
            ),
            graph,
        )

        follow_up = DispatchRequest(
            action="ingest",
            thread_id="run-1",
            team_preset=DEFAULT_TEAM_PRESET,
            workspace_root=_uncanonical_spelling(workspace),
            recursion_limit=25,
            model_assignment=_assignment("current"),
            graph_definition=_definition(workspace),
        )
        resolved = await manager.get_or_compile_graph(follow_up)

        assert resolved is graph
        assert manager.graph_count == 1

    @pytest.mark.asyncio
    async def test_each_run_compiles_its_own_graph_and_reuses_it(
        self, workspace: Path
    ) -> None:
        """Real compilation: a second run never receives the first run's graph."""
        manager = self._manager()

        assignment = _assignment("current")

        def dispatch(thread_id: str) -> DispatchRequest:
            return DispatchRequest(
                action="ingest",
                thread_id=thread_id,
                team_preset=DEFAULT_TEAM_PRESET,
                workspace_root=str(workspace),
                recursion_limit=25,
                model_assignment=assignment,
                graph_definition=_definition(workspace),
            )

        first = await manager.get_or_compile_graph(dispatch("run-1"))
        second = await manager.get_or_compile_graph(dispatch("run-2"))
        again = await manager.get_or_compile_graph(dispatch("run-1"))

        assert first is not None and second is not None
        assert first is not second
        assert again is first
        assert manager.graph_count == 2

    @pytest.mark.asyncio
    async def test_a_thread_cannot_reuse_a_graph_for_another_assignment(
        self, workspace: Path
    ) -> None:
        manager = self._manager()
        graph = self._graph()
        accepted = _assignment("accepted")
        manager.register_compiled_graph(
            "run-1",
            (
                DEFAULT_TEAM_PRESET,
                str(workspace),
                False,
                model_assignment_digest(accepted),
                _definition(workspace).digest(),
            ),
            graph,
        )

        with pytest.raises(
            GraphCompilationError,
            match="dispatch compilation authority does not match the bound run",
        ):
            await manager.get_or_compile_graph(
                DispatchRequest(
                    action="ingest",
                    thread_id="run-1",
                    team_preset=DEFAULT_TEAM_PRESET,
                    workspace_root=str(workspace),
                    recursion_limit=25,
                    model_assignment=_assignment("changed"),
                    graph_definition=_definition(workspace),
                )
            )

    @pytest.mark.asyncio
    async def test_eviction_does_not_remove_the_thread_assignment_binding(
        self, workspace: Path
    ) -> None:
        manager = self._manager()
        accepted = _assignment("accepted")
        manager.register_compiled_graph(
            "run-1",
            (
                DEFAULT_TEAM_PRESET,
                str(workspace),
                False,
                model_assignment_digest(accepted),
                _definition(workspace).digest(),
            ),
            self._graph(),
        )
        manager.evict_cached_graphs()

        with pytest.raises(GraphCompilationError, match="bound run"):
            await manager.get_or_compile_graph(
                DispatchRequest(
                    action="ingest",
                    thread_id="run-1",
                    team_preset=DEFAULT_TEAM_PRESET,
                    workspace_root=str(workspace),
                    recursion_limit=25,
                    model_assignment=_assignment("changed"),
                    graph_definition=_definition(workspace),
                )
            )

    @pytest.mark.asyncio
    async def test_concurrent_first_dispatches_bind_once_and_reject_a_competitor(
        self, workspace: Path
    ) -> None:
        class ControlledManager(GraphLifecycleManager):
            def __init__(self) -> None:
                super().__init__(
                    checkpointer=InMemorySaver(),
                    bridge=WorkerBridge(
                        api_url="http://127.0.0.1:1", worker_id="identity"
                    ),
                    producer=RunEventProducer(),
                    token_store=RunTokenStore(),
                    catalog_store=RunCatalogStore(),
                )
                self.started = asyncio.Event()
                self.release = asyncio.Event()
                self.compile_count = 0

            @override
            async def _compile_graph(
                self, req: DispatchRequest
            ) -> RegisteredCompiledGraph:
                del req
                self.compile_count += 1
                self.started.set()
                await self.release.wait()
                return TestOneWorkspaceOneGraphEntry._graph()

        manager = ControlledManager()

        def request(assignment: dict[str, FrozenLaneAssignment]) -> DispatchRequest:
            return DispatchRequest(
                action="ingest",
                thread_id="run-race",
                team_preset=DEFAULT_TEAM_PRESET,
                workspace_root=str(workspace),
                recursion_limit=25,
                model_assignment=assignment,
                graph_definition=_definition(workspace),
            )

        first = asyncio.create_task(
            manager.get_or_compile_graph(request(_assignment("a")))
        )
        await manager.started.wait()
        competing = asyncio.create_task(
            manager.get_or_compile_graph(request(_assignment("b")))
        )
        manager.release.set()
        assert await first is not None
        with pytest.raises(GraphCompilationError, match="bound run"):
            await competing
        assert manager.compile_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_equal_first_dispatches_share_the_compilation(
        self, workspace: Path
    ) -> None:
        class ControlledManager(GraphLifecycleManager):
            def __init__(self) -> None:
                super().__init__(
                    checkpointer=InMemorySaver(),
                    bridge=WorkerBridge(
                        api_url="http://127.0.0.1:1", worker_id="identity"
                    ),
                    producer=RunEventProducer(),
                    token_store=RunTokenStore(),
                    catalog_store=RunCatalogStore(),
                )
                self.started = asyncio.Event()
                self.release = asyncio.Event()
                self.compile_count = 0

            @override
            async def _compile_graph(
                self, req: DispatchRequest
            ) -> RegisteredCompiledGraph:
                del req
                self.compile_count += 1
                self.started.set()
                await self.release.wait()
                return TestOneWorkspaceOneGraphEntry._graph()

        manager = ControlledManager()
        req = DispatchRequest(
            action="ingest",
            thread_id="run-equal-race",
            team_preset=DEFAULT_TEAM_PRESET,
            workspace_root=str(workspace),
            recursion_limit=25,
            model_assignment=_assignment("same"),
            graph_definition=_definition(workspace),
        )
        first = asyncio.create_task(manager.get_or_compile_graph(req))
        await manager.started.wait()
        duplicate = asyncio.create_task(manager.get_or_compile_graph(req))
        manager.release.set()
        assert await first is await duplicate
        assert manager.compile_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_runs_of_one_compilation_identity_compile_apart(
        self, workspace: Path
    ) -> None:
        class ControlledManager(GraphLifecycleManager):
            def __init__(self) -> None:
                super().__init__(
                    checkpointer=InMemorySaver(),
                    bridge=WorkerBridge(
                        api_url="http://127.0.0.1:1", worker_id="identity"
                    ),
                    producer=RunEventProducer(),
                    token_store=RunTokenStore(),
                    catalog_store=RunCatalogStore(),
                )
                self.started = asyncio.Event()
                self.release = asyncio.Event()
                self.compile_count = 0

            @override
            async def _compile_graph(
                self, req: DispatchRequest
            ) -> RegisteredCompiledGraph:
                del req
                self.compile_count += 1
                self.started.set()
                await self.release.wait()
                return TestOneWorkspaceOneGraphEntry._graph()

        manager = ControlledManager()

        def request(thread_id: str) -> DispatchRequest:
            return DispatchRequest(
                action="ingest",
                thread_id=thread_id,
                team_preset=DEFAULT_TEAM_PRESET,
                workspace_root=str(workspace),
                recursion_limit=25,
                model_assignment=_assignment("same"),
                graph_definition=_definition(workspace),
            )

        first = asyncio.create_task(manager.get_or_compile_graph(request("run-a")))
        await manager.started.wait()
        second = asyncio.create_task(manager.get_or_compile_graph(request("run-b")))
        await asyncio.sleep(0)
        # The second run does not wait on the first run's compile to share it:
        # a shared graph would hand both runs the same model instances.
        assert manager.compile_count == 2
        assert manager.compile_flight_count == 2
        manager.release.set()
        assert await first is not await second
        assert manager.compile_count == 2
        assert manager.compile_flight_count == 0

    @pytest.mark.asyncio
    async def test_distinct_assignment_digests_compile_independently(
        self, workspace: Path
    ) -> None:
        class ControlledManager(GraphLifecycleManager):
            def __init__(self) -> None:
                super().__init__(
                    checkpointer=InMemorySaver(),
                    bridge=WorkerBridge(
                        api_url="http://127.0.0.1:1", worker_id="identity"
                    ),
                    producer=RunEventProducer(),
                    token_store=RunTokenStore(),
                    catalog_store=RunCatalogStore(),
                )
                self.both_started = asyncio.Event()
                self.release = asyncio.Event()
                self.compile_count = 0

            @override
            async def _compile_graph(
                self, req: DispatchRequest
            ) -> RegisteredCompiledGraph:
                del req
                self.compile_count += 1
                if self.compile_count == 2:
                    self.both_started.set()
                await self.release.wait()
                return TestOneWorkspaceOneGraphEntry._graph()

        manager = ControlledManager()

        def request(thread_id: str, model_name: str) -> DispatchRequest:
            return DispatchRequest(
                action="ingest",
                thread_id=thread_id,
                team_preset=DEFAULT_TEAM_PRESET,
                workspace_root=str(workspace),
                recursion_limit=25,
                model_assignment=_assignment(model_name),
                graph_definition=_definition(workspace),
            )

        first = asyncio.create_task(
            manager.get_or_compile_graph(request("run-a", "model-a"))
        )
        second = asyncio.create_task(
            manager.get_or_compile_graph(request("run-b", "model-b"))
        )
        await asyncio.wait_for(manager.both_started.wait(), timeout=1)
        assert manager.compile_count == 2
        assert manager.compile_flight_count == 2
        manager.release.set()
        assert await first is not None
        assert await second is not None
        assert manager.compile_flight_count == 0

    @pytest.mark.asyncio
    async def test_real_checkpoint_read_timeout_cleans_all_compile_state(
        self, workspace: Path, checkpointer: AsyncSqliteSaver
    ) -> None:
        manager = GraphLifecycleManager(
            checkpointer=checkpointer,
            bridge=WorkerBridge(api_url="http://127.0.0.1:1", worker_id="identity"),
            producer=RunEventProducer(),
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
            checkpoint_read_timeout_seconds=0.02,
        )
        await checkpointer.lock.acquire()
        try:
            with pytest.raises(GraphCompilationError, match="read timed out"):
                await manager.get_or_compile_graph(
                    DispatchRequest(
                        action="ingest",
                        thread_id="held-read",
                        team_preset=DEFAULT_TEAM_PRESET,
                        workspace_root=str(workspace),
                        recursion_limit=25,
                        model_assignment=_assignment("current"),
                        graph_definition=_definition(workspace),
                    )
                )
        finally:
            checkpointer.lock.release()

        assert manager.thread_binding_count == 0
        assert manager.compile_flight_count == 0

    @pytest.mark.asyncio
    async def test_fresh_worker_refuses_a_digest_that_disagrees_with_checkpoint(
        self, workspace: Path
    ) -> None:
        accepted_digest = model_assignment_digest(_assignment("accepted"))

        class DigestCheckpointer:
            async def aget_tuple(self, _config: object) -> object:
                return SimpleNamespace(
                    checkpoint={
                        "channel_values": {"model_assignment_digest": accepted_digest}
                    }
                )

        manager = GraphLifecycleManager(
            checkpointer=cast("Any", DigestCheckpointer()),
            bridge=WorkerBridge(api_url="http://127.0.0.1:1", worker_id="identity"),
            producer=RunEventProducer(),
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )
        with pytest.raises(
            GraphCompilationError, match="durable compilation authority is incompatible"
        ):
            await manager.get_or_compile_graph(
                DispatchRequest(
                    action="ingest",
                    thread_id="run-fresh-worker",
                    team_preset=DEFAULT_TEAM_PRESET,
                    workspace_root=str(workspace),
                    recursion_limit=25,
                    model_assignment=_assignment("changed"),
                    graph_definition=_definition(workspace),
                )
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stored_digest", ["A" * 64, "not-a-digest"])
    async def test_fresh_worker_refuses_noncurrent_checkpoint_binding_before_compile(
        self, workspace: Path, stored_digest: str | None
    ) -> None:
        class DigestCheckpointer:
            async def aget_tuple(self, _config: object) -> object:
                values = {}
                if stored_digest is not None:
                    values["model_assignment_digest"] = stored_digest
                return SimpleNamespace(checkpoint={"channel_values": values})

        class CompileTrap(GraphLifecycleManager):
            @override
            async def _compile_graph(
                self, req: DispatchRequest
            ) -> RegisteredCompiledGraph:
                raise AssertionError(
                    f"compiled incompatible checkpoint for {req.thread_id}"
                )

        manager = CompileTrap(
            checkpointer=cast("Any", DigestCheckpointer()),
            bridge=WorkerBridge(api_url="http://127.0.0.1:1", worker_id="identity"),
            producer=RunEventProducer(),
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )
        with pytest.raises(GraphCompilationError, match="incompatible"):
            await manager.get_or_compile_graph(
                DispatchRequest(
                    action="ingest",
                    thread_id="run-noncurrent-checkpoint",
                    team_preset=DEFAULT_TEAM_PRESET,
                    workspace_root=str(workspace),
                    recursion_limit=25,
                    model_assignment=_assignment("current"),
                    graph_definition=_definition(workspace),
                )
            )

    @pytest.mark.asyncio
    async def test_compile_failure_releases_the_thread_lock_for_an_exact_retry(
        self, workspace: Path
    ) -> None:
        class FailOnceManager(GraphLifecycleManager):
            def __init__(self) -> None:
                super().__init__(
                    checkpointer=InMemorySaver(),
                    bridge=WorkerBridge(
                        api_url="http://127.0.0.1:1", worker_id="identity"
                    ),
                    producer=RunEventProducer(),
                    token_store=RunTokenStore(),
                    catalog_store=RunCatalogStore(),
                )
                self.calls = 0

            @override
            async def _compile_graph(
                self, req: DispatchRequest
            ) -> RegisteredCompiledGraph:
                del req
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("controlled compile failure")
                return TestOneWorkspaceOneGraphEntry._graph()

        manager = FailOnceManager()
        req = DispatchRequest(
            action="ingest",
            thread_id="run-retry",
            team_preset=DEFAULT_TEAM_PRESET,
            workspace_root=str(workspace),
            recursion_limit=25,
            model_assignment=_assignment("same"),
            graph_definition=_definition(workspace),
        )
        with pytest.raises(GraphCompilationError, match="controlled compile failure"):
            await manager.get_or_compile_graph(req)
        assert manager.compile_flight_count == 0
        assert await manager.get_or_compile_graph(req) is not None
        assert manager.calls == 2
