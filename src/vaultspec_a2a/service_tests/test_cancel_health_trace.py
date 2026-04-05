"""Cancel, health, and trace certification against the real compose stack."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .harness import ServiceStack


def _wait_for_state(
    stack: ServiceStack,
    thread_id: str,
    predicate,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = stack.get_thread_state(thread_id)
        last_state = state
        if predicate(state):
            return state
        time.sleep(1.0)
    raise AssertionError(f"timed out waiting for thread {thread_id}: {last_state}")


def test_cancel_transitions_to_terminal_cancelled(service_stack: ServiceStack) -> None:
    """A running thread can be cancelled through the public REST API."""
    created = service_stack.create_thread(
        initial_message="Start a long-running task and then cancel it.",
        team_preset="mock-looping",
        title="service cancel",
    )
    thread_id = created["thread_id"]

    active = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: (
            state.get("status") == "running" or state.get("last_sequence", 0) > 0
        ),
        timeout=30.0,
    )
    service_stack.record(f"cancel-active:{thread_id}", active)

    cancelling = service_stack.cancel_thread(thread_id)
    assert cancelling["cancelled"] is True
    assert cancelling["status"] == "cancelling"

    cancelled = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "cancelled",
    )
    service_stack.record(f"cancelled-state:{thread_id}", cancelled)

    assert cancelled["status"] == "cancelled"


def test_health_and_trace_surface_are_observable(
    service_stack: ServiceStack,
    service_started_at: float,
) -> None:
    """The stack reports health and exports a real Jaeger trace."""
    health = service_stack.health()
    service_stack.record("health-final", health)

    assert health["status"] == "ok"
    assert health["checks"]["database"]["status"] == "ok"
    assert health["checks"]["checkpoint"]["status"] == "ok"
    assert health["checks"]["worker"]["status"] == "ok"
    assert health["worker_connected"] is True
    assert health["sqlite_fallback"]["active"] is True

    services = service_stack.jaeger_services()
    service_names = set(services.get("data", []))
    assert "vaultspec-a2a" in service_names

    created = service_stack.create_thread(
        initial_message="Run a short task so worker IPC generates traceable traffic.",
        team_preset="mock-success-single",
        title="service trace probe",
    )
    thread_id = created["thread_id"]
    traced_thread = _wait_for_state(
        service_stack,
        thread_id,
        lambda state: state.get("status") == "completed",
        timeout=60.0,
    )
    service_stack.record(f"trace-probe:{thread_id}", traced_thread)

    start_us = int(service_started_at * 1_000_000)
    found = False
    traces: dict[str, Any] = {}
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        end_us = int(time.time() * 1_000_000)
        traces = service_stack.jaeger_traces(
            service="vaultspec-a2a",
            start_us=start_us,
            end_us=end_us,
            limit=50,
        )
        for trace in traces.get("data", []):
            processes = trace.get("processes", {})
            trace_services = {
                process.get("serviceName")
                for process in processes.values()
                if isinstance(process, dict)
            }
            spans = trace.get("spans", [])
            operation_names = {
                span.get("operationName") for span in spans if isinstance(span, dict)
            }
            if "vaultspec-a2a" in trace_services and operation_names & {
                "POST /internal/events",
                "POST /internal/events/batch",
            }:
                found = True
                break
        if found:
            break
        time.sleep(1.0)

    assert found, "expected a Jaeger trace for worker-originated IPC traffic"
