"""Tests for context window management: estimation, compaction, handoff."""

import json

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..context import (
    compact_context,
    estimate_tokens,
    prepare_handoff,
    should_compact,
)
from ..state import TeamState


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """Tests for the ~4 chars/token heuristic estimator."""

    def test_empty_list(self) -> None:
        """Empty message list estimates zero tokens."""
        assert estimate_tokens([]) == 0

    def test_single_message(self) -> None:
        """400-character message estimates 100 tokens (400 / 4)."""
        msg = HumanMessage(content="a" * 400)
        expected = 100
        assert estimate_tokens([msg]) == expected

    def test_multiple_messages(self) -> None:
        """Token counts from all messages are summed (40/4 + 80/4 = 30)."""
        msgs = [HumanMessage(content="a" * 40), AIMessage(content="b" * 80)]
        # 40/4 + 80/4 = 10 + 20 = 30
        expected = 30
        assert estimate_tokens(msgs) == expected

    def test_multipart_content(self) -> None:
        """Multi-part content dicts use the 'text' key for length (11 // 4 = 2)."""
        msg = HumanMessage(content=[{"text": "hello world"}])
        # "hello world" is 11 chars → 11 // 4 = 2
        expected = 2
        assert estimate_tokens([msg]) == expected

    def test_list_of_strings_content(self) -> None:
        """String-list content items are each counted by length (4 + 4 = 8 → 2)."""
        msg = HumanMessage(content=["abcd", "efgh"])
        # 4 + 4 = 8 chars → 2 tokens
        expected = 2
        assert estimate_tokens([msg]) == expected


# ---------------------------------------------------------------------------
# Should compact
# ---------------------------------------------------------------------------


class TestShouldCompact:
    """Tests for the compaction threshold check."""

    def _make_state(self, char_count: int) -> TeamState:
        """Build a minimal state with a message of the given char count."""
        return {
            "messages": [HumanMessage(content="x" * char_count)],
            "next": "",
            "current_plan": [],
            "artifacts": [],
            "active_agent": "",
            "thread_id": "",
            "token_usage": {},
        }

    def test_below_threshold(self) -> None:
        """400 chars → 100 tokens is below 80% of 200 (160), so no compaction."""
        state = self._make_state(400)
        assert should_compact(state, max_tokens=200) is False

    def test_above_threshold(self) -> None:
        """800 chars → 200 tokens exceeds 80% of 200 (160), so compaction triggers."""
        state = self._make_state(800)
        assert should_compact(state, max_tokens=200) is True

    def test_exactly_at_threshold(self) -> None:
        """At the exact 80%-of-200 boundary the strictly-greater check returns False."""
        # 640 chars → 160 tokens, threshold is 80% of 200 = 160
        # 160 > 160 is False
        state = self._make_state(640)
        assert should_compact(state, max_tokens=200) is False

    def test_empty_messages(self) -> None:
        """Empty message list never triggers compaction."""
        state: TeamState = {
            "messages": [],
            "next": "",
            "current_plan": [],
            "artifacts": [],
            "active_agent": "",
            "thread_id": "",
            "token_usage": {},
            "loop_count": 0,
        }
        assert should_compact(state, max_tokens=100) is False


# ---------------------------------------------------------------------------
# Compact context
# ---------------------------------------------------------------------------


class TestCompactContext:
    """Tests for the context compaction strategy."""

    def test_no_compaction_needed(self) -> None:
        """State with few tokens is returned unchanged."""
        state: TeamState = {
            "messages": [HumanMessage(content="short")],
            "next": "",
            "current_plan": [],
            "artifacts": [],
            "active_agent": "",
            "thread_id": "",
            "token_usage": {},
        }
        result = compact_context(state, max_tokens=10000)
        assert len(result["messages"]) == 1

    def test_preserves_system_prefix(self) -> None:
        """After compaction the first message is still the original system message."""
        sys_msg = SystemMessage(content="You are a helpful assistant.")
        messages = [sys_msg]
        # Add many messages to exceed the budget
        for i in range(20):
            messages.append(HumanMessage(content=f"Message {i} " + "x" * 200))
            messages.append(AIMessage(content=f"Response {i} " + "y" * 200))

        state: TeamState = {
            "messages": messages,
            "next": "",
            "current_plan": [],
            "artifacts": [],
            "active_agent": "",
            "thread_id": "",
            "token_usage": {},
        }

        result = compact_context(state, max_tokens=200)

        # First message should still be the original system message
        assert isinstance(result["messages"][0], SystemMessage)
        assert result["messages"][0].content == sys_msg.content
        # Second should be the compaction summary
        assert isinstance(result["messages"][1], SystemMessage)
        summary_content = result["messages"][1].content
        assert isinstance(summary_content, str)
        assert "compacted" in summary_content.lower()
        # Should have fewer messages than original
        assert len(result["messages"]) < len(messages)

    def test_preserves_recent_messages(self) -> None:
        """The most recently added message survives compaction."""
        messages: list = [SystemMessage(content="system")]
        for i in range(10):
            messages.append(HumanMessage(content=f"msg-{i} " + "a" * 100))
        last_msg = HumanMessage(content="the-final-question")
        messages.append(last_msg)

        state: TeamState = {
            "messages": messages,
            "next": "",
            "current_plan": [],
            "artifacts": [],
            "active_agent": "",
            "thread_id": "",
            "token_usage": {},
        }

        result = compact_context(state, max_tokens=100)
        # The most recent message should be preserved
        assert any("the-final-question" in str(m.content) for m in result["messages"])

    def test_does_not_mutate_original(self) -> None:
        """compact_context returns a new dict and never modifies the input."""
        messages = [
            SystemMessage(content="sys"),
            HumanMessage(content="x" * 4000),
            AIMessage(content="y" * 4000),
        ]
        state: TeamState = {
            "messages": list(messages),
            "next": "",
            "current_plan": [],
            "artifacts": [],
            "active_agent": "",
            "thread_id": "",
            "token_usage": {},
            "loop_count": 0,
        }
        original_count = len(state["messages"])
        compact_context(state, max_tokens=50)
        assert len(state["messages"]) == original_count

    def test_empty_messages(self) -> None:
        """Compacting a state with no messages returns an empty messages list."""
        state: TeamState = {
            "messages": [],
            "next": "",
            "current_plan": [],
            "artifacts": [],
            "active_agent": "",
            "thread_id": "",
            "token_usage": {},
            "loop_count": 0,
        }
        result = compact_context(state, max_tokens=100)
        assert result["messages"] == []

    def test_non_message_fields_preserved(self) -> None:
        """All non-messages fields are copied unchanged into the compacted state."""
        state: TeamState = {
            "messages": [HumanMessage(content="x" * 4000)],
            "next": "coder",
            "current_plan": [{"step": "test", "status": "done", "agent": "a"}],
            "artifacts": [{"id": "1", "path": "/f", "type": "file", "created_by": "a"}],
            "active_agent": "planner",
            "thread_id": "t-1",
            "token_usage": {"a": {"input": 1, "output": 1, "total": 2}},
            "loop_count": 0,
        }
        result = compact_context(state, max_tokens=10)
        assert result["next"] == "coder"
        assert result["current_plan"] == state["current_plan"]
        assert result["artifacts"] == state["artifacts"]
        assert result["active_agent"] == "planner"
        assert result["thread_id"] == "t-1"
        assert result["token_usage"] == state["token_usage"]


# ---------------------------------------------------------------------------
# Handoff preparation
# ---------------------------------------------------------------------------


class TestPrepareHandoff:
    """Tests for the clean handoff builder (ADR-002)."""

    @pytest.fixture
    def full_state(self) -> TeamState:
        """Build a fully-populated TeamState for handoff tests."""
        return {
            "messages": [
                SystemMessage(content="objective"),
                HumanMessage(content="do stuff"),
                AIMessage(content="reasoning loop 1"),
                AIMessage(content="reasoning loop 2"),
            ],
            "next": "coder",
            "current_plan": [
                {"step": "research", "status": "done", "agent": "planner"},
                {"step": "implement", "status": "pending", "agent": "coder"},
            ],
            "artifacts": [
                {"id": "a1", "path": "/main.py", "type": "file", "created_by": "coder"},
            ],
            "active_agent": "planner",
            "thread_id": "thread-42",
            "token_usage": {
                "planner": {"input": 500, "output": 200, "total": 700},
            },
            "loop_count": 0,
        }

    def test_strips_messages(self, full_state: TeamState) -> None:
        """Handoff dict omits the messages field entirely."""
        result = prepare_handoff(full_state, target_agent="coder")
        assert "messages" not in result

    def test_sets_target_agent(self, full_state: TeamState) -> None:
        """active_agent is set to the supplied target_agent string."""
        result = prepare_handoff(full_state, target_agent="reviewer")
        assert result["active_agent"] == "reviewer"

    def test_preserves_plan(self, full_state: TeamState) -> None:
        """current_plan is copied verbatim into the handoff dict."""
        result = prepare_handoff(full_state, target_agent="coder")
        assert result["current_plan"] == full_state["current_plan"]

    def test_preserves_artifacts(self, full_state: TeamState) -> None:
        """Artifacts list is copied verbatim into the handoff dict."""
        result = prepare_handoff(full_state, target_agent="coder")
        assert result["artifacts"] == full_state["artifacts"]

    def test_preserves_thread_id(self, full_state: TeamState) -> None:
        """thread_id is forwarded unchanged."""
        result = prepare_handoff(full_state, target_agent="coder")
        assert result["thread_id"] == "thread-42"

    def test_preserves_token_usage(self, full_state: TeamState) -> None:
        """token_usage is copied into the handoff dict for bookkeeping."""
        result = prepare_handoff(full_state, target_agent="coder")
        assert result["token_usage"] == full_state["token_usage"]

    def test_handoff_is_json_serializable(self, full_state: TeamState) -> None:
        """The handoff dict contains only JSON-native primitives."""
        result = prepare_handoff(full_state, target_agent="coder")
        json.dumps(result)

    def test_does_not_mutate_original(self, full_state: TeamState) -> None:
        """prepare_handoff never mutates the source state."""
        original_agent = full_state["active_agent"]
        prepare_handoff(full_state, target_agent="reviewer")
        assert full_state["active_agent"] == original_agent
