"""Tests for worker/gateway IPC serialization helpers."""

from __future__ import annotations

from ...graph.events import PermissionRequest
from ...ipc.serializers import _event_type, sequenced_to_dict
from ...streaming.types import SequencedEvent


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


def test_every_domain_event_subclass_is_mapped_by_the_relay_catalog() -> None:
    """No worker event may fall through the relay's wire-type catalog.

    ``ipc/serializers.py`` tags each of the eleven event classes with a wire-type
    string for the IPC relay in one enumeration, and nothing statically ties it
    to the event classes. There is no closed union to exhaust: ``DomainEvent`` is
    a base class, so a type checker cannot prove the enumeration complete. This
    test is the guarantee instead, and it is deliberately driven off the SUBCLASS
    SET rather than a hand-written list, so a twelfth event class cannot be added
    without appearing here.

    A miss is silent. The relay returns ``None``, which its own docstring explains
    reaches subscribers "stripped of everything that made it meaningful, while
    the worker-side emission looks perfectly healthy" - and names the event this
    already shipped undeliverable once. A silent miss is exactly what an
    in-process test of the emitter cannot see, which is why the assertion lives
    here, against the enumeration, rather than in the emitter's own suite.
    """
    from ...graph import events as events_module
    from ...graph.events import DomainEvent

    subclasses = sorted(
        (
            value
            for value in vars(events_module).values()
            if isinstance(value, type)
            and issubclass(value, DomainEvent)
            and value is not DomainEvent
        ),
        key=lambda cls: cls.__name__,
    )
    assert subclasses, "no DomainEvent subclasses discovered"

    unmapped = [
        cls.__name__ for cls in subclasses if _event_type(cls.__new__(cls)) is None
    ]
    assert not unmapped, (
        "these domain events relay with no wire type and are silently "
        f"degraded on delivery: {unmapped}"
    )
