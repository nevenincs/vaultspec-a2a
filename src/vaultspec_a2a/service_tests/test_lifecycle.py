"""Lifecycle certification against the real compose stack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..testing import wait_for_run_status
from ._state import thread_state

if TYPE_CHECKING:
    from .harness import ServiceStack


def test_thread_lifecycle_reaches_completion(service_stack: ServiceStack) -> None:
    """Create a thread and prove the public lifecycle reaches completion."""
    created = service_stack.create_thread(
        initial_message="Run the deterministic success preset.",
        team_preset="mock-success-single",
        title="service lifecycle",
    )
    thread_id = created["run_id"]

    terminal = wait_for_run_status(
        lambda: thread_state(service_stack, thread_id),
        lambda state: state.get("status") == "completed",
    )
    service_stack.record(f"lifecycle-state:{thread_id}", terminal)

    listed = service_stack.list_threads(status="completed")
    assert any(run["run_id"] == thread_id for run in listed["runs"])
    assert terminal["status"] == "completed"
    assert terminal["messages"], "completed lifecycle should leave replayable messages"
