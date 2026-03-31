"""Lifecycle certification against the real compose stack."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .harness import ServiceStack


def _wait_for_thread_state(
    stack: ServiceStack,
    thread_id: str,
    predicate,
    *,
    timeout: float = 120.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        state = stack.get_thread_state(thread_id)
        last_state = state
        if predicate(state):
            return state
        time.sleep(1.0)
    raise AssertionError(f"timed out waiting for thread {thread_id}: {last_state}")


def test_thread_lifecycle_reaches_completion(service_stack: ServiceStack) -> None:
    """Create a thread and prove the public lifecycle reaches completion."""
    created = service_stack.create_thread(
        initial_message="Run the deterministic success preset.",
        team_preset="mock-success-single",
        title="service lifecycle",
    )
    thread_id = created["thread_id"]

    terminal = _wait_for_thread_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
    )
    service_stack.record(f"lifecycle-state:{thread_id}", terminal)

    listed = service_stack.list_threads(status="completed")
    assert any(t["thread_id"] == thread_id for t in listed["threads"])
    assert terminal["status"] == "completed"
    assert terminal["messages"], "completed lifecycle should leave replayable messages"
