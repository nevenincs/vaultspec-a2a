"""Tests for thread/snapshots.py — pure functions and Layer 1 dataclasses."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ...graph.enums import AgentLifecycleState, Provider
from ..enums import RepairStatus, ThreadStatus
from ..models import PlanEntry
from ..snapshots import (
    PLAN_APPROVAL_PAUSE_CAUSES,
    ThreadStateData,
    build_agent_descriptor,
    classify_message_role,
    classify_permission_pause_reason,
    derive_message_id,
    extract_message_timestamp,
    is_permission_event,
    is_terminal_event,
    normalize_artifacts,
    normalize_plan_entries,
    record_repair_posture,
    stamp_message_created_at,
)

# ---------------------------------------------------------------------------
# classify_message_role
# ---------------------------------------------------------------------------


def test_classify_human_message() -> None:
    assert classify_message_role(HumanMessage(content="hi")) == "user"


def test_classify_ai_message() -> None:
    assert classify_message_role(AIMessage(content="hey")) == "assistant"


def test_classify_tool_message() -> None:
    msg = ToolMessage(content="ok", tool_call_id="tc-1")
    assert classify_message_role(msg) == "tool"


def test_classify_unknown_message() -> None:
    """Non-standard message objects fall through to 'system'."""

    class CustomMsg:
        content = "x"

    assert classify_message_role(CustomMsg()) == "system"


# ---------------------------------------------------------------------------
# extract_message_timestamp
# ---------------------------------------------------------------------------


def test_extract_timestamp_from_response_metadata() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    msg = AIMessage(
        content="hello",
        response_metadata={"created_at": ts},
    )
    assert extract_message_timestamp(msg) == ts


def test_extract_timestamp_from_string() -> None:
    msg = AIMessage(
        content="hello",
        response_metadata={"created_at": "2026-01-01T00:00:00+00:00"},
    )
    result = extract_message_timestamp(msg)
    assert result == datetime(2026, 1, 1, tzinfo=UTC)


def test_an_unstamped_message_reports_no_time_not_the_read_time() -> None:
    assert extract_message_timestamp(HumanMessage(content="hi")) is None


def test_a_stamped_message_reports_when_it_was_produced() -> None:
    produced = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    msg = stamp_message_created_at(HumanMessage(content="hi"), at=produced)
    assert extract_message_timestamp(msg) == produced


def test_stamping_never_rewrites_a_recorded_time() -> None:
    produced = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    msg = stamp_message_created_at(AIMessage(content="x"), at=produced)
    stamp_message_created_at(msg, at=datetime(2027, 1, 1, tzinfo=UTC))
    assert extract_message_timestamp(msg) == produced


# ---------------------------------------------------------------------------
# derive_message_id
# ---------------------------------------------------------------------------


def test_derive_message_id_uses_stored_id() -> None:
    assert derive_message_id("user", "hi", "stored-123") == "stored-123"


def test_derive_message_id_generates_hash_fallback() -> None:
    result = derive_message_id("user", "hi", None)
    assert len(result) == 32
    assert result == derive_message_id("user", "hi", None)


def test_derive_message_id_differs_by_role() -> None:
    a = derive_message_id("user", "hi", None)
    b = derive_message_id("assistant", "hi", None)
    assert a != b


# ---------------------------------------------------------------------------
# normalize_plan_entries
# ---------------------------------------------------------------------------


def test_normalize_plan_entries_from_dicts() -> None:
    raw = [
        {"content": "step 1", "status": "done", "priority": "high"},
        {"content": "step 2"},
    ]
    result = normalize_plan_entries(raw)
    assert len(result) == 2
    assert result[0] == PlanEntry(content="step 1", status="done", priority="high")
    assert result[1] == PlanEntry(content="step 2", status="pending", priority="medium")


def test_normalize_plan_entries_passes_through_dataclass() -> None:
    entry = PlanEntry(content="direct", status="done", priority="low")
    result = normalize_plan_entries([entry])
    assert result == [entry]


def test_normalize_plan_entries_skips_non_dict_non_entry() -> None:
    result = normalize_plan_entries(["not a dict", 42])
    assert result == []


# ---------------------------------------------------------------------------
# normalize_artifacts
# ---------------------------------------------------------------------------


def test_normalize_artifacts_from_dicts() -> None:
    raw = [{"artifact_id": "a1", "filename": "f.txt"}]
    result = normalize_artifacts(raw)
    assert result == [
        {"artifact_id": "a1", "filename": "f.txt", "content": "", "complete": True}
    ]


def test_normalize_artifacts_skips_non_dict() -> None:
    assert normalize_artifacts(["bad", 42]) == []


# ---------------------------------------------------------------------------
# Event classification predicates
# ---------------------------------------------------------------------------


def test_is_terminal_event_true() -> None:
    assert is_terminal_event({"event_type": "thread_terminal", "status": "completed"})


def test_is_terminal_event_false_wrong_type() -> None:
    assert not is_terminal_event({"event_type": "other", "status": "completed"})


def test_is_terminal_event_false_unknown_status() -> None:
    assert not is_terminal_event({"event_type": "thread_terminal", "status": "bogus"})


def test_is_permission_event_true() -> None:
    assert is_permission_event({"type": "permission_request"})
    assert is_permission_event({"type": "permission_resolved"})


def test_is_permission_event_false() -> None:
    assert not is_permission_event({"type": "agent_status"})


def test_classify_permission_pause_reason_plan_approval() -> None:
    assert classify_permission_pause_reason("plan_approval") == "plan_approval_request"


def test_classify_permission_pause_reason_regular() -> None:
    assert classify_permission_pause_reason("bash") == "bash"


def test_classify_permission_pause_reason_none() -> None:
    assert classify_permission_pause_reason(None) == "permission_request"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_plan_approval_pause_causes_contains_both_variants() -> None:
    assert "plan_approval" in PLAN_APPROVAL_PAUSE_CAUSES
    assert "plan_approval_request" in PLAN_APPROVAL_PAUSE_CAUSES


# ---------------------------------------------------------------------------
# record_repair_posture
# ---------------------------------------------------------------------------


def _snapshot() -> ThreadStateData:
    return ThreadStateData(thread_id="t1", status=ThreadStatus.RUNNING, last_sequence=0)


def test_record_repair_posture_writes_the_posture_and_its_readiness_together() -> None:
    snapshot = _snapshot()
    record_repair_posture(snapshot, "needs_reconciliation")
    assert snapshot.repair_status is RepairStatus.NEEDS_RECONCILIATION
    assert snapshot.execution_readiness is RepairStatus.NEEDS_RECONCILIATION


def test_record_repair_posture_clears_both_fields_for_no_posture() -> None:
    snapshot = _snapshot()
    record_repair_posture(snapshot, RepairStatus.REPLAY_GAP)
    record_repair_posture(snapshot, None)
    assert snapshot.repair_status is None
    assert snapshot.execution_readiness is None


def test_record_repair_posture_refuses_a_posture_outside_the_vocabulary() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="not a valid RepairStatus"):
        record_repair_posture(snapshot, "bogus")
    assert snapshot.repair_status is None
    assert snapshot.execution_readiness is None


# ---------------------------------------------------------------------------
# build_agent_descriptor
# ---------------------------------------------------------------------------


def test_build_agent_descriptor_reads_provider_and_model_from_node_metadata() -> None:
    """The shared projection seam carries the resolved model assignment."""
    descriptor = build_agent_descriptor(
        {
            "agent_id": "coder",
            "node_name": "coder",
            "provider": "zai",
            "model_name": "catalog-model",
            "role": "implementer",
            "display_name": "Coder",
            "description": "Writes code.",
        },
        AgentLifecycleState.WORKING,
        thread_id="thread-1",
    )
    assert descriptor.provider is Provider.ZAI
    assert descriptor.model_name == "catalog-model"
    assert descriptor.state is AgentLifecycleState.WORKING


def test_build_agent_descriptor_leaves_unresolved_assignment_unknown() -> None:
    """An agent observed before its model resolves reports None, not a guess."""
    descriptor = build_agent_descriptor(
        {"agent_id": "planner", "node_name": "planner", "provider": ""},
        AgentLifecycleState.SUBMITTED,
        thread_id="thread-1",
    )
    assert descriptor.provider is None
    assert descriptor.model_name is None


def test_build_agent_descriptor_rejects_an_unrecognised_provider() -> None:
    """Config drift must not smuggle an arbitrary string onto the wire enum."""
    descriptor = build_agent_descriptor(
        {"agent_id": "x", "node_name": "x", "provider": "not-a-provider"},
        AgentLifecycleState.IDLE,
        thread_id="thread-1",
    )
    assert descriptor.provider is None
