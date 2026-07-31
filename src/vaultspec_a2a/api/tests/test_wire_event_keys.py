"""The relayed event-type key pair must hold wherever a payload is normalised.

A relayed event names its type under two keys, ``type`` and ``event_type``, and
both have live readers. The rule that keeps them in step had three near-copies,
and the normaliser could repair only one direction, so the same event
classified differently depending only on which producer built it.

These tests bind the normaliser and the three relay predicates to that rule
directly, so a payload is classifiable under whichever key names its type.
"""

from __future__ import annotations

import pytest

from ...thread.enums import ThreadStatus
from ...thread.snapshots import (
    is_permission_event,
    is_progress_event,
    is_terminal_event,
    normalize_wire_event_type,
)

# ---------------------------------------------------------------------------
# The bypass: a WS-origin terminal payload reaching a real client
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The seam: mirroring is bidirectional, and classification agrees either way
# ---------------------------------------------------------------------------


def test_normalizer_repairs_a_type_only_payload() -> None:
    """A payload naming its type under ``type`` alone leaves carrying both.

    The direction the SSE-side normaliser structurally could not repair: it
    returned early whenever ``type`` was present, so an ``event_type`` reader
    downstream saw an untyped payload.
    """
    normalized = normalize_wire_event_type({"type": "thread_terminal", "status": "ok"})
    assert normalized["type"] == "thread_terminal"
    assert normalized["event_type"] == "thread_terminal"


def test_normalizer_repairs_an_event_type_only_payload() -> None:
    """A payload naming its type under ``event_type`` alone leaves with both."""
    normalized = normalize_wire_event_type({"event_type": "message_chunk"})
    assert normalized["type"] == "message_chunk"
    assert normalized["event_type"] == "message_chunk"


def test_normalizer_leaves_an_untyped_payload_untyped() -> None:
    """A payload naming no type is not stamped with an empty one."""
    normalized = normalize_wire_event_type({"thread_id": "t1"})
    assert "type" not in normalized
    assert "event_type" not in normalized


def test_normalizing_is_idempotent() -> None:
    """Re-normalising an already-mirrored payload changes nothing."""
    once = normalize_wire_event_type({"event_type": "agent_status", "state": "busy"})
    assert normalize_wire_event_type(once) == once


@pytest.mark.parametrize(
    ("event_type", "classifier"),
    [
        ("thread_terminal", None),
        ("permission_request", is_permission_event),
        ("agent_status", is_progress_event),
    ],
)
def test_classifiers_agree_whichever_key_names_the_type(
    event_type: str, classifier
) -> None:
    """The three relay predicates classify a payload identically under either key.

    They previously read different keys - terminal read ``event_type``, the other
    two read ``type`` - so the same event classified differently depending only
    on which producer built it.
    """
    under_type = {"type": event_type, "status": ThreadStatus.FAILED.value}
    under_event_type = {"event_type": event_type, "status": ThreadStatus.FAILED.value}

    if classifier is None:
        assert is_terminal_event(under_type)
        assert is_terminal_event(under_event_type)
    else:
        assert classifier(under_type)
        assert classifier(under_event_type)
