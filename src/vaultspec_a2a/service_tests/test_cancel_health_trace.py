"""Cancel, health, and trace certification against the real compose stack."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ..testing.payloads import (
    json_object,
    json_object_list,
    required_bool,
    required_text,
)
from ._state import wait_for_state

if TYPE_CHECKING:
    from ..providers._json_contract import JsonObject
    from .harness import ServiceStack


_TEXT_LIST = TypeAdapter(list[str])


def _text_list(value: object, *, at: str) -> list[str]:
    """Read a strict list of text values from a real public payload."""
    try:
        return _TEXT_LIST.validate_python(value, strict=True)
    except ValidationError as exc:
        raise TypeError(f"expected a text list at {at}: {exc}") from exc


def _is_active(state: JsonObject) -> bool:
    """Recognise a running or advancing thread before cancellation."""
    sequence = state.get("last_sequence")
    return state.get("status") == "running" or (
        isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0
    )


def _is_cancelled(state: JsonObject) -> bool:
    """Recognise the durable terminal cancellation state."""
    return state.get("status") == "cancelled"


def _is_completed(state: JsonObject) -> bool:
    """Recognise the durable completed state used for trace generation."""
    return state.get("status") == "completed"


def test_cancel_transitions_to_terminal_cancelled(service_stack: ServiceStack) -> None:
    """A running thread can be cancelled through the public REST API."""
    created = service_stack.create_thread(
        initial_message="Start a long-running task and then cancel it.",
        team_preset="mock-looping",
        title="service cancel",
    )
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )

    active = wait_for_state(
        service_stack,
        thread_id,
        _is_active,
        timeout=30.0,
    )
    service_stack.record(f"cancel-active:{thread_id}", active)

    cancelling = json_object(
        service_stack.cancel_thread(thread_id), at="cancel response"
    )
    assert required_bool(cancelling, "cancelled", at="cancel response") is True
    assert required_text(cancelling, "status", at="cancel response") == "cancelling"

    cancelled = wait_for_state(
        service_stack,
        thread_id,
        _is_cancelled,
    )
    service_stack.record(f"cancelled-state:{thread_id}", cancelled)

    assert required_text(cancelled, "status", at="cancelled thread") == "cancelled"


def test_health_and_trace_surface_are_observable(
    service_stack: ServiceStack,
    service_started_at: float,
) -> None:
    """The stack reports health and exports a real Jaeger trace."""
    health = json_object(service_stack.health(), at="health response")
    service_stack.record("health-final", health)

    assert required_text(health, "status", at="health response") == "ok"
    checks = json_object(health.get("checks"), at="health checks")
    for check_name in ("database", "checkpoint", "worker"):
        check = json_object(checks.get(check_name), at=f"health checks.{check_name}")
        assert required_text(check, "status", at=f"health checks.{check_name}") == "ok"
    assert required_bool(health, "worker_connected", at="health response") is True
    sqlite_fallback = json_object(health.get("sqlite_fallback"), at="sqlite fallback")
    assert required_bool(sqlite_fallback, "active", at="sqlite fallback") is True

    services = json_object(service_stack.jaeger_services(), at="Jaeger services")
    service_names = set(_text_list(services.get("data"), at="Jaeger services.data"))
    assert "vaultspec-a2a" in service_names

    created = service_stack.create_thread(
        initial_message="Run a short task so worker IPC generates traceable traffic.",
        team_preset="mock-success-single",
        title="service trace probe",
    )
    thread_id = required_text(
        json_object(created, at="created thread"), "run_id", at="created thread"
    )
    traced_thread = wait_for_state(
        service_stack,
        thread_id,
        _is_completed,
        timeout=60.0,
    )
    service_stack.record(f"trace-probe:{thread_id}", traced_thread)

    start_us = int(service_started_at * 1_000_000)
    found = False
    traces: JsonObject = {}
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        end_us = int(time.time() * 1_000_000)
        traces = json_object(
            service_stack.jaeger_traces(
                service="vaultspec-a2a",
                start_us=start_us,
                end_us=end_us,
                limit=50,
            ),
            at="Jaeger traces",
        )
        for trace in json_object_list(traces.get("data"), at="Jaeger traces.data"):
            processes = json_object(trace.get("processes"), at="Jaeger trace processes")
            trace_services = {
                service_name
                for process in processes.values()
                for service_name in [
                    json_object(process, at="Jaeger process").get("serviceName")
                ]
                if isinstance(service_name, str)
            }
            spans = json_object_list(trace.get("spans"), at="Jaeger trace spans")
            operation_names = {
                operation_name
                for span in spans
                for operation_name in [span.get("operationName")]
                if isinstance(operation_name, str)
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
