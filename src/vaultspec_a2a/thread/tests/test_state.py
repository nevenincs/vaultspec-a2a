"""Tests for TeamState schema, reducers, and JSON serialization round-trip."""

import json
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import Checkpoint
from langgraph.checkpoint.base.id import uuid6
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ..state import (
    TeamState,
    _append_artifacts,
    _append_research_findings,
    _merge_token_usage,
    _merge_unique_strs,
    _replace_plan,
)

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

# ---------------------------------------------------------------------------
# Reducer unit tests
# ---------------------------------------------------------------------------


class TestAppendArtifacts:
    """Tests for the artifact append-deduplicate reducer."""

    def test_appends_new_items(self) -> None:
        """Two distinct artifact ids produce a result list of length two."""
        existing = [{"id": "a1", "path": "/f1", "type": "file", "created_by": "coder"}]
        new = [{"id": "a2", "path": "/f2", "type": "file", "created_by": "coder"}]
        result = _append_artifacts(existing, new)
        expected_len = 2
        assert len(result) == expected_len
        assert result[1]["id"] == "a2"

    def test_deduplicates_by_id(self) -> None:
        """Duplicate artifact id is not appended; first occurrence wins."""
        existing = [{"id": "a1", "path": "/f1", "type": "file", "created_by": "coder"}]
        new = [{"id": "a1", "path": "/f1-updated", "type": "file", "created_by": "x"}]
        result = _append_artifacts(existing, new)
        assert len(result) == 1
        # First occurrence wins
        assert result[0]["path"] == "/f1"

    def test_empty_existing(self) -> None:
        """Appending to an empty list returns a single-item list."""
        new_artifact = {"id": "a1", "path": "/f", "type": "file", "created_by": ""}
        result = _append_artifacts([], [new_artifact])
        assert len(result) == 1

    def test_empty_new(self) -> None:
        """Appending an empty list leaves the existing list unchanged."""
        existing = [{"id": "a1", "path": "/f", "type": "file", "created_by": ""}]
        result = _append_artifacts(existing, [])
        assert result == existing


class TestMergeUniqueStrs:
    """Tests for the append-and-deduplicate string reducer (authoring refs)."""

    def test_appends_new_ids(self) -> None:
        result = _merge_unique_strs(["cs:1"], ["cs:2"])
        assert result == ["cs:1", "cs:2"]

    def test_deduplicates_preserving_order(self) -> None:
        result = _merge_unique_strs(["cs:1", "cs:2"], ["cs:2", "cs:3"])
        assert result == ["cs:1", "cs:2", "cs:3"]

    def test_empty_new_keeps_existing(self) -> None:
        result = _merge_unique_strs(["cs:1"], [])
        assert result == ["cs:1"]

    def test_does_not_mutate_existing(self) -> None:
        existing = ["cs:1"]
        _merge_unique_strs(existing, ["cs:2"])
        assert existing == ["cs:1"]


class TestAppendResearchFindings:
    """Tests for the append-only research-findings reducer."""

    def test_appends_findings_in_order(self) -> None:
        existing = [{"claim": "c1", "locators": ["f.py:1"], "source_thread": "t1"}]
        new = [{"claim": "c2", "locators": ["g.py:2"], "source_thread": "t2"}]
        result = _append_research_findings(existing, new)
        assert result == [existing[0], new[0]]

    def test_accumulates_parallel_branches(self) -> None:
        """Two branches contributing the same claim text both accumulate.

        Findings are append-only with no dedup: parallel researchers legitimately
        surface overlapping claims from distinct threads, and synthesis needs the
        full set.
        """
        existing = [{"claim": "dup", "locators": [], "source_thread": "t1"}]
        new = [{"claim": "dup", "locators": [], "source_thread": "t2"}]
        result = _append_research_findings(existing, new)
        assert len(result) == 2
        assert result[0]["source_thread"] == "t1"
        assert result[1]["source_thread"] == "t2"

    def test_empty_new_keeps_existing(self) -> None:
        existing = [{"claim": "c1", "locators": [], "source_thread": "t1"}]
        result = _append_research_findings(existing, [])
        assert result == existing

    def test_does_not_mutate_existing(self) -> None:
        existing = [{"claim": "c1", "locators": [], "source_thread": "t1"}]
        _append_research_findings(
            existing, [{"claim": "c2", "locators": [], "source_thread": "t2"}]
        )
        assert existing == [{"claim": "c1", "locators": [], "source_thread": "t1"}]


class TestMergeTokenUsage:
    """Tests for the additive token-usage reducer."""

    def test_accumulates_counters(self) -> None:
        """Existing and new counters for the same agent are added together."""
        existing = {"agent-a": {"input": 100, "output": 50, "total": 150}}
        new = {"agent-a": {"input": 20, "output": 10, "total": 30}}
        result = _merge_token_usage(existing, new)
        assert result["agent-a"] == {"input": 120, "output": 60, "total": 180}

    def test_adds_new_agent(self) -> None:
        """A new agent key is added without affecting existing agents."""
        existing = {"agent-a": {"input": 10, "output": 5, "total": 15}}
        new = {"agent-b": {"input": 30, "output": 20, "total": 50}}
        result = _merge_token_usage(existing, new)
        assert "agent-a" in result
        assert "agent-b" in result
        expected_total = 50
        assert result["agent-b"]["total"] == expected_total

    def test_does_not_mutate_existing(self) -> None:
        """The existing dict is never modified in place."""
        existing = {"agent-a": {"input": 10, "output": 5, "total": 15}}
        original_inner = dict(existing["agent-a"])
        _merge_token_usage(existing, {"agent-a": {"input": 1, "output": 1, "total": 2}})
        assert existing["agent-a"] == original_inner

    def test_empty_merge(self) -> None:
        """Merging an empty dict returns the existing values unchanged."""
        existing = {"agent-a": {"input": 10, "output": 5, "total": 15}}
        result = _merge_token_usage(existing, {})
        assert result == existing


class TestReplacePlan:
    """Tests for the full-replacement plan reducer."""

    def test_replaces_with_new(self) -> None:
        """A non-empty new list fully replaces the old plan."""
        old = [{"step": "research", "status": "done", "agent": "planner"}]
        new = [{"step": "implement", "status": "pending", "agent": "coder"}]
        result = _replace_plan(old, new)
        assert result == new

    def test_empty_new_clears_plan(self) -> None:
        """An empty list explicitly clears the plan
        (T12 fix — was silently discarded).
        """
        old = [{"step": "research", "status": "done", "agent": "planner"}]
        result = _replace_plan(old, [])
        assert result == []

    def test_none_new_keeps_existing(self) -> None:
        """None leaves the existing plan in place (reducer called with no update)."""
        old = [{"step": "research", "status": "done", "agent": "planner"}]
        result = _replace_plan(old, None)
        assert result == old


# ---------------------------------------------------------------------------
# JSON serialization round-trip
# ---------------------------------------------------------------------------


class TestStateJsonRoundTrip:
    """Verify that the non-message fields of TeamState survive JSON encode/decode."""

    @pytest.fixture
    def sample_state(self) -> dict:
        """Build a representative state dict with all new fields populated."""
        return {
            "next": "coder",
            "active_agent": "planner",
            "thread_id": "thread-001",
            "current_plan": [
                {"step": "research", "status": "done", "agent": "planner"},
                {"step": "implement", "status": "pending", "agent": "coder"},
            ],
            "artifacts": [
                {
                    "id": "art-1",
                    "path": "/src/main.py",
                    "type": "file",
                    "created_by": "coder",
                },
            ],
            "token_usage": {
                "planner": {"input": 500, "output": 200, "total": 700},
                "coder": {"input": 300, "output": 150, "total": 450},
            },
        }

    def test_round_trip_json(self, sample_state: dict) -> None:
        """All non-message fields must survive JSON encode -> decode."""
        encoded = json.dumps(sample_state)
        decoded = json.loads(encoded)
        assert decoded == sample_state

    def test_messages_field_excluded_from_json_check(self) -> None:
        """Messages are handled by LangGraph's serializer, not JSON directly.

        This test confirms all non-message fields are JSON-native primitives.
        """
        state: dict = {
            "messages": [HumanMessage(content="hi")],
            "next": "",
            "active_agent": "",
            "thread_id": "",
            "current_plan": [],
            "artifacts": [],
            "token_usage": {},
        }
        # Strip messages before JSON check (LangGraph handles these)
        serializable = {k: v for k, v in state.items() if k != "messages"}
        # T3: actually verify the JSON round-trip produces valid output
        result = json.dumps(serializable)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["thread_id"] == ""
        assert parsed["current_plan"] == []
        assert parsed["artifacts"] == []


# ---------------------------------------------------------------------------
# TypedDict structural checks
# ---------------------------------------------------------------------------


class TestTeamStateStructure:
    """Verify TeamState has all expected keys."""

    def test_has_required_keys(self) -> None:
        """TeamState annotations include exactly the expected field names."""
        expected = {
            "messages",
            "next",
            "current_plan",
            "artifacts",
            "active_agent",
            "thread_id",
            "token_usage",
            "loop_count",
            "routing_error",
            # SDD blackboard awareness fields
            "active_feature",
            "pipeline_phase",
            "vault_index",
            "validation_errors",
            # transient mounted document content
            "mounted_context",
            # task queue pointer
            "current_task_id",
            # authoring proposal references
            "authoring_session_id",
            "authoring_changeset_ids",
            "authoring_proposal_ids",
            # plan approval gate
            "approval_status",
            "approval_request_id",
            # document phase machine
            "research_findings",
            "gate_phase",
            "gate_verdict",
            "gate_pending_proposal_id",
            # mid-run clarification (agent-flow ADR D5)
            "clarification_questions",
            "clarification_answers",
            # workspace root path
            "workspace_root",
            "feedback_batch_id",
        }
        actual = set(TeamState.__annotations__)
        assert expected == actual


# ---------------------------------------------------------------------------
# Checkpoint hydration boundary
# ---------------------------------------------------------------------------


class TestUndeclaredCheckpointKeys:
    """The schema, not the checkpoint row, decides what a node can read.

    A key retired from ``TeamState`` cannot be reintroduced by a checkpoint
    written while it still existed. That is what makes retiring a key a real
    retirement rather than a rename that leaves the old value live, and it is
    why gates read exactly one key instead of a key plus its predecessor.
    """

    @pytest.mark.asyncio
    async def test_retired_key_in_a_persisted_checkpoint_never_reaches_a_node(
        self,
        tmp_path: "Path",
    ) -> None:
        seen: list[dict[str, Any]] = []

        def probe(state: TeamState) -> dict[str, Any]:
            seen.append(dict(state))
            return {"active_agent": "probe"}

        builder = StateGraph(cast("Any", TeamState))
        builder.add_node("probe", probe)
        builder.add_edge(START, "probe")
        builder.add_edge("probe", END)

        db = tmp_path / "checkpoints.sqlite"
        async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
            graph = builder.compile(checkpointer=saver)
            config: RunnableConfig = {
                "configurable": {"thread_id": "retired-key-thread"},
            }
            await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="start")],
                    "active_agent": "start",
                    "thread_id": "retired-key-thread",
                    "artifacts": [],
                    "current_plan": [],
                    "token_usage": {},
                },
                config,
            )

            # Forge the pre-retirement row: a real checkpoint whose persisted
            # channel_values carry a key the current schema no longer declares.
            stored = await saver.aget_tuple(config)
            assert stored is not None
            original = stored.checkpoint
            forged = Checkpoint(
                v=original["v"],
                id=str(uuid6(clock_seq=-2)),
                ts=original["ts"],
                channel_values={
                    **original["channel_values"],
                    "plan_approved": True,
                },
                channel_versions={
                    **original["channel_versions"],
                    "plan_approved": "00000000000000000000000000000002.retired",
                },
                versions_seen=original["versions_seen"],
                updated_channels=original["updated_channels"],
            )
            await saver.aput(stored.config, forged, stored.metadata or {}, {})

            reread = await saver.aget_tuple(config)
            assert reread is not None
            assert reread.checkpoint["channel_values"]["plan_approved"] is True

            seen.clear()
            await graph.ainvoke({"active_agent": "resumed"}, config)
            resumed_state = seen[-1]
            assert "plan_approved" not in resumed_state
            assert resumed_state.get("plan_approved") is None

            snapshot = await graph.aget_state(config)
            assert "plan_approved" not in snapshot.values
