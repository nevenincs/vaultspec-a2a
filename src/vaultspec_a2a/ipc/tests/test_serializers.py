"""Tests for worker/gateway IPC serialization helpers."""

from __future__ import annotations

from vaultspec_a2a.graph.events import PermissionRequest
from vaultspec_a2a.ipc.serializers import sequenced_to_dict
from vaultspec_a2a.streaming.aggregator import SequencedEvent


def test_sequenced_to_dict_includes_permission_event_type_fields() -> None:
    """Relayed permission events must carry type metadata for gateway handlers."""
    event = PermissionRequest(
        thread_id="thread-123",
        agent_id="agent-123",
        timestamp=1.0,
        request_id="req-123",
        description="Approval required",
        options=[{"option_id": "approve", "name": "Approve", "kind": "allow_once"}],
        tool_call="session_request_permission",
    )

    payload = sequenced_to_dict(SequencedEvent(event=event, sequence=7))

    assert payload["type"] == "permission_request"
    assert payload["event_type"] == "permission_request"
    assert payload["request_id"] == "req-123"
    assert payload["sequence"] == 7
