"""Tests for the helper dataclasses: TokenUsageEntry, PlanStep, ArtifactRef.

Exercises to_dict/from_dict round-trips, frozen immutability, and edge-case
handling (missing keys, extra keys, default values).
"""

import pytest

from ..models import ArtifactRef, PlanStep, TokenUsageEntry


# ---------------------------------------------------------------------------
# TokenUsageEntry
# ---------------------------------------------------------------------------


class TestTokenUsageEntry:
    """Tests for TokenUsageEntry dataclass."""

    def test_to_dict_returns_inner_counters(self) -> None:
        """to_dict excludes agent_id and uses 'input'/'output' keys."""
        entry = TokenUsageEntry(
            agent_id="coder", input_tokens=100, output_tokens=50, total=150
        )
        d = entry.to_dict()
        assert d == {"input": 100, "output": 50, "total": 150}
        assert "agent_id" not in d

    def test_from_dict_round_trip(self) -> None:
        """from_dict -> to_dict produces the original dict."""
        original = {"input": 200, "output": 80, "total": 280}
        entry = TokenUsageEntry.from_dict("planner", original)
        assert entry.agent_id == "planner"
        assert entry.to_dict() == original

    def test_from_dict_missing_keys_default_to_zero(self) -> None:
        """Missing keys in the source dict default to 0."""
        entry = TokenUsageEntry.from_dict("agent-x", {})
        assert entry.input_tokens == 0
        assert entry.output_tokens == 0
        assert entry.total == 0

    def test_frozen_immutability(self) -> None:
        """Frozen dataclass rejects attribute assignment."""
        entry = TokenUsageEntry(agent_id="a", input_tokens=1, output_tokens=2, total=3)
        with pytest.raises(AttributeError):
            entry.agent_id = "b"  # type: ignore[misc]

    def test_default_field_values(self) -> None:
        """Only agent_id is required; counters default to 0."""
        entry = TokenUsageEntry(agent_id="minimal")
        assert entry.input_tokens == 0
        assert entry.output_tokens == 0
        assert entry.total == 0


# ---------------------------------------------------------------------------
# PlanStep
# ---------------------------------------------------------------------------


class TestPlanStep:
    """Tests for PlanStep dataclass."""

    def test_to_dict_includes_all_fields(self) -> None:
        """to_dict returns step, status, and agent."""
        step = PlanStep(step="research", status="done", agent="planner")
        d = step.to_dict()
        assert d == {"step": "research", "status": "done", "agent": "planner"}

    def test_from_dict_round_trip(self) -> None:
        """from_dict -> to_dict produces the original dict."""
        original = {"step": "implement", "status": "pending", "agent": "coder"}
        ps = PlanStep.from_dict(original)
        assert ps.to_dict() == original

    def test_from_dict_missing_keys_use_defaults(self) -> None:
        """Missing keys get default values: status='pending', agent=''."""
        ps = PlanStep.from_dict({"step": "test"})
        assert ps.step == "test"
        assert ps.status == "pending"
        assert ps.agent == ""

    def test_from_dict_empty_dict(self) -> None:
        """Completely empty dict uses all defaults."""
        ps = PlanStep.from_dict({})
        assert ps.step == ""
        assert ps.status == "pending"
        assert ps.agent == ""

    def test_frozen_immutability(self) -> None:
        """Frozen dataclass rejects attribute assignment."""
        ps = PlanStep(step="x")
        with pytest.raises(AttributeError):
            ps.step = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ArtifactRef
# ---------------------------------------------------------------------------


class TestArtifactRef:
    """Tests for ArtifactRef dataclass."""

    def test_to_dict_includes_all_fields(self) -> None:
        """to_dict returns id, path, type, and created_by."""
        ref = ArtifactRef(
            id="art-1", path="/src/main.py", type="file", created_by="coder"
        )
        d = ref.to_dict()
        assert d == {
            "id": "art-1",
            "path": "/src/main.py",
            "type": "file",
            "created_by": "coder",
        }

    def test_from_dict_round_trip(self) -> None:
        """from_dict -> to_dict produces the original dict."""
        original = {
            "id": "art-2",
            "path": "/docs/readme.md",
            "type": "doc",
            "created_by": "writer",
        }
        ar = ArtifactRef.from_dict(original)
        assert ar.to_dict() == original

    def test_from_dict_missing_keys_use_defaults(self) -> None:
        """Missing keys get default values: type='file', created_by=''."""
        ar = ArtifactRef.from_dict({"id": "a1", "path": "/x"})
        assert ar.type == "file"
        assert ar.created_by == ""

    def test_from_dict_empty_dict(self) -> None:
        """Completely empty dict uses all defaults."""
        ar = ArtifactRef.from_dict({})
        assert ar.id == ""
        assert ar.path == ""
        assert ar.type == "file"
        assert ar.created_by == ""

    def test_frozen_immutability(self) -> None:
        """Frozen dataclass rejects attribute assignment."""
        ar = ArtifactRef(id="x", path="/y")
        with pytest.raises(AttributeError):
            ar.id = "z"  # type: ignore[misc]

    def test_different_type_values(self) -> None:
        """ArtifactRef supports arbitrary type strings (file, diff, doc, etc.)."""
        for artifact_type in ("file", "diff", "doc", "log"):
            ar = ArtifactRef(id="t", path="/p", type=artifact_type)
            assert ar.type == artifact_type
            assert ar.to_dict()["type"] == artifact_type
