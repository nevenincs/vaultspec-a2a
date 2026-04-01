"""Tests for thread/snapshots.py — pure functions and Layer 1 dataclasses."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ..models import PlanEntry
from ..snapshots import (
    PLAN_APPROVAL_PAUSE_CAUSES,
    TERMINAL_STATUS_MAP,
    AgentData,
    ArtifactData,
    ExecutionTaskData,
    MessageData,
    PermissionData,
    PermissionOptionData,
    ThreadStateData,
    ToolCallData,
    classify_message_role,
    classify_permission_pause_reason,
    derive_message_id,
    extract_message_timestamp,
    finalize_snapshot_replay_status,
    is_permission_event,
    is_progress_event,
    is_terminal_event,
    normalize_artifacts,
    normalize_plan_entries,
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


def test_extract_timestamp_fallback_to_now() -> None:
    msg = HumanMessage(content="hi")
    result = extract_message_timestamp(msg)
    assert isinstance(result, datetime)


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
# finalize_snapshot_replay_status
# ---------------------------------------------------------------------------


def test_finalize_durable() -> None:
    snap = ThreadStateData(thread_id="t1", status="running", last_sequence=0)
    result = finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=True,
        checkpoint_present=True,
        checkpoint_error=False,
        thread_status="running",
    )
    assert result.replay_status == "durable"


def test_finalize_checkpoint_error() -> None:
    snap = ThreadStateData(thread_id="t1", status="running", last_sequence=0)
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=True,
        thread_status="running",
    )
    assert snap.replay_status == "unknown"
    assert snap.snapshot_complete is False


def test_finalize_best_effort() -> None:
    snap = ThreadStateData(thread_id="t1", status="running", last_sequence=0)
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=True,
        checkpoint_error=False,
        thread_status="running",
    )
    assert snap.replay_status == "best_effort"
    assert snap.snapshot_complete is False


def test_finalize_submitted_no_checkpoint() -> None:
    snap = ThreadStateData(thread_id="t1", status="submitted", last_sequence=0)
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="submitted",
    )
    assert snap.replay_status == "unknown"
    assert snap.snapshot_complete is True


def test_finalize_gap_detected() -> None:
    snap = ThreadStateData(thread_id="t1", status="running", last_sequence=0)
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="running",
    )
    assert snap.replay_status == "gap_detected"
    assert "checkpoint_missing" in snap.degraded_reasons
    assert snap.repair_status == "checkpoint_unavailable"
    assert snap.execution_readiness == "checkpoint_unavailable"


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


def test_is_progress_event_true() -> None:
    assert is_progress_event({"type": "agent_status"})
    assert is_progress_event({"type": "message_chunk"})
    assert is_progress_event({"type": "tool_call_start"})


def test_is_progress_event_false() -> None:
    assert not is_progress_event({"type": "unknown_thing"})


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


def test_terminal_status_map_keys() -> None:
    assert set(TERMINAL_STATUS_MAP) == {"completed", "failed", "cancelled"}


# ---------------------------------------------------------------------------
# D-12 dataclass round-trip: dataclass -> asdict -> Pydantic model_validate
# ---------------------------------------------------------------------------


def test_message_data_round_trip() -> None:
    from ...api.schemas.snapshots import MessageSnapshot

    data = MessageData(
        message_id="m1",
        role="user",
        content="hi",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pydantic_obj = MessageSnapshot.model_validate(asdict(data))
    assert pydantic_obj.message_id == "m1"
    assert pydantic_obj.role == "user"


def test_tool_call_data_round_trip() -> None:
    from ...api.schemas.snapshots import ToolCallSnapshot

    data = ToolCallData(
        tool_call_id="tc1",
        title="bash",
        kind="execute",
        status="pending",
    )
    pydantic_obj = ToolCallSnapshot.model_validate(asdict(data))
    assert pydantic_obj.tool_call_id == "tc1"


def test_artifact_data_round_trip() -> None:
    from ...api.schemas.snapshots import ArtifactSnapshot

    data = ArtifactData(
        artifact_id="a1",
        filename="test.py",
        content="print('hello')",
        complete=True,
    )
    pydantic_obj = ArtifactSnapshot.model_validate(asdict(data))
    assert pydantic_obj.artifact_id == "a1"


def test_permission_data_round_trip() -> None:
    from ...api.schemas.snapshots import _PermissionSnapshot

    data = PermissionData(
        request_id="r1",
        description="approve this",
        options=[
            PermissionOptionData(
                option_id="allow_once",
                name="Allow Once",
                kind="allow_once",
            )
        ],
        tool_call="bash",
    )
    pydantic_obj = _PermissionSnapshot.model_validate(asdict(data))
    assert pydantic_obj.request_id == "r1"
    assert len(pydantic_obj.options) == 1


def test_agent_data_round_trip() -> None:
    from ...api.schemas.snapshots import _AgentSnapshot

    data = AgentData(
        agent_id="agent-1",
        node_name="supervisor",
        state="idle",
        role="manager",
    )
    pydantic_obj = _AgentSnapshot.model_validate(asdict(data))
    assert pydantic_obj.agent_id == "agent-1"


def test_execution_task_data_round_trip() -> None:
    from ...api.schemas.snapshots import ExecutionTaskSnapshot

    data = ExecutionTaskData(
        task_id="task-1",
        name="supervisor",
        path=["supervisor"],
        has_error=False,
    )
    pydantic_obj = ExecutionTaskSnapshot.model_validate(asdict(data))
    assert pydantic_obj.task_id == "task-1"


def test_thread_state_data_round_trip() -> None:
    from ...api.schemas.snapshots import ThreadStateSnapshot

    data = ThreadStateData(
        thread_id="t1",
        status="running",
        last_sequence=42,
        messages=[
            MessageData(
                message_id="m1",
                role="user",
                content="hi",
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
    )
    pydantic_obj = ThreadStateSnapshot.model_validate(asdict(data))
    assert pydantic_obj.thread_id == "t1"
    assert pydantic_obj.last_sequence == 42
    assert len(pydantic_obj.messages) == 1
