"""Tests for the domain-action to dispatch-wire-literal narrowing."""

from __future__ import annotations

import pytest

from vaultspec_a2a.ipc.schemas import DispatchRequest, to_dispatch_action
from vaultspec_a2a.thread.enums import ControlActionType


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (ControlActionType.INGEST, "ingest"),
        (ControlActionType.RESUME, "resume"),
        (ControlActionType.CANCEL, "cancel"),
    ],
)
def test_narrows_each_dispatch_action_to_its_wire_literal(
    action: ControlActionType, expected: str
) -> None:
    narrowed = to_dispatch_action(action)
    assert narrowed == expected
    # The narrowed value is accepted by the wire contract without coercion.
    request = DispatchRequest(action=narrowed, thread_id="t1", recursion_limit=25)
    assert request.action == expected


def test_rejects_a_non_dispatch_control_action() -> None:
    with pytest.raises(ValueError, match="not a dispatch action"):
        to_dispatch_action(ControlActionType.PERMISSION_REQUEST_CREATED)
