"""The active project is minted once and named in one spelling everywhere.

A run's project used to be re-derived at every boundary it crossed. Admission
resolved the caller's spelling locally and dispatched that; the durable record
kept the caller's original; and every later dispatch - follow-up, clarification
response, verdict resume, crash recovery - read the durable one back. Two
strings for one directory, agreeing only by coincidence, and the worker's graph
cache keyed on the raw string, so a single workspace occupied two entries and
recompiled its graph on the first follow-up.

These tests drive the real seams that produced the split: the admission
function, the dispatch schema every construction site validates through, and
the worker's own cache-key former and registration seam.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from ...api.tests.clarification_harness import new_state_graph
from ...context.metadata import ThreadMetadata
from ...control._thread_metadata import dispatchable_workspace_root
from ...database.thread_repository import normalize_workspace_identity
from ...ipc.schemas import DispatchRequest, canonical_project_root
from ...streaming.aggregator import EventAggregator
from ...thread.errors import ConfigError
from ...thread.state import TeamState
from ...worker.catalog_store import RunCatalogStore
from ...worker.graph_lifecycle import (
    GraphLifecycleManager,
    RegisteredCompiledGraph,
    graph_cache_key,
)
from ...worker.ipc import WorkerBridge
from ...worker.token_store import RunTokenStore
from ..thread_service import process_metadata

if TYPE_CHECKING:
    from pathlib import Path


def _uncanonical_spelling(workspace: Path) -> str:
    """Return a second, equally valid spelling of *workspace*.

    A detour through a sibling directory plus POSIX separators reproduces, with
    no symlink privileges and on either platform, exactly the shape the split
    took: the same directory written two ways.
    """
    return str(workspace.parent / "sibling" / ".." / workspace.name).replace("\\", "/")


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
    """S07 - admission is where the run's project spelling is decided."""

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


class TestDispatchCarriesTheMintedProject:
    """S08 - the wire mints, so no construction site can dispatch a raw path."""

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
    """S20 - ``TeamState.workspace_root`` must be written, not merely declared.

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
            team_preset="preset",
            workspace_root=_uncanonical_spelling(workspace),
            content=content,
            recursion_limit=25,
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
        builder.add_node("observe", observe)
        builder.add_edge("__start__", "observe")
        builder.add_edge("observe", "__end__")
        graph = builder.compile(checkpointer=InMemorySaver())

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
    """S14 support - the run's authoring submitter is built on its own project."""

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
            aggregator=EventAggregator(),
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )

        with pytest.raises(ConfigError, match="must name the project it authors into"):
            await manager._build_proposal_submitter(None)


class TestOneWorkspaceOneGraphEntry:
    """S09 - the worker's graph cache holds one entry per workspace."""

    @staticmethod
    def _manager() -> GraphLifecycleManager:
        return GraphLifecycleManager(
            checkpointer=InMemorySaver(),
            bridge=WorkerBridge(api_url="http://127.0.0.1:1", worker_id="identity"),
            aggregator=EventAggregator(),
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )

    @staticmethod
    def _graph() -> RegisteredCompiledGraph:
        def finish_node(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        builder = new_state_graph()
        builder.add_node("finish", finish_node)
        builder.add_edge("__start__", "finish")
        builder.add_edge("finish", "__end__")
        return builder.compile(checkpointer=InMemorySaver())

    def test_two_spellings_key_the_same_entry(self, workspace: Path) -> None:
        assert graph_cache_key("preset", str(workspace), False) == graph_cache_key(
            "preset", _uncanonical_spelling(workspace), False
        )

    def test_a_project_less_key_is_still_a_key(self) -> None:
        """A run with no project still keys, so the mint cannot break cancel."""
        assert graph_cache_key("preset", None, True) == ("preset", None, True)

    def test_two_threads_on_one_workspace_share_one_cached_graph(
        self, workspace: Path
    ) -> None:
        """The registration seam must not shadow the entry a dispatch would find.

        Registering under two spellings of one directory used to leave two
        entries, so the second thread's turn recompiled a graph the worker
        already held.
        """
        manager = self._manager()
        graph = self._graph()

        manager.register_compiled_graph(
            "run-1", ("preset", str(workspace), False), graph
        )
        manager.register_compiled_graph(
            "run-2", ("preset", _uncanonical_spelling(workspace), False), graph
        )

        assert manager.graph_count == 1
        assert manager.cache_key_for_thread("run-1") == manager.cache_key_for_thread(
            "run-2"
        )

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
            "run-1", ("preset", str(workspace), False), graph
        )

        follow_up = DispatchRequest(
            action="ingest",
            thread_id="run-2",
            team_preset="preset",
            workspace_root=_uncanonical_spelling(workspace),
            recursion_limit=25,
        )
        resolved = await manager.get_or_compile_graph(follow_up)

        assert resolved is graph
        assert manager.graph_count == 1
