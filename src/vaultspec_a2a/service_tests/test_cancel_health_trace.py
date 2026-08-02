"""Cancel, health, and trace certification against the real compose stack."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .harness import ServiceStack


_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
_TEXT_LIST = TypeAdapter(list[str])


def _json_object(value: object, *, at: str) -> dict[str, object]:
    """Narrow a real service payload to an object at its public boundary."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"expected an object at {at}: {exc}") from exc


def _json_object_list(value: object, *, at: str) -> list[dict[str, object]]:
    """Narrow a real service payload to an object list at its public boundary."""
    try:
        return _JSON_OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"expected an object list at {at}: {exc}") from exc


def _text_list(value: object, *, at: str) -> list[str]:
    """Read a strict list of text values from a real public payload."""
    try:
        return _TEXT_LIST.validate_python(value, strict=True)
    except ValidationError as exc:
        raise TypeError(f"expected a text list at {at}: {exc}") from exc


def _required_text(body: dict[str, object], field: str, *, at: str) -> str:
    """Read one required text field from a validated service payload."""
    value = body.get(field)
    if not isinstance(value, str):
        raise AssertionError(f"{at}.{field} was not text: {value!r}")
    return value


def _required_bool(body: dict[str, object], field: str, *, at: str) -> bool:
    """Read one required boolean field from a validated service payload."""
    value = body.get(field)
    if not isinstance(value, bool):
        raise AssertionError(f"{at}.{field} was not boolean: {value!r}")
    return value


def _thread_state(stack: ServiceStack, thread_id: str) -> dict[str, object]:
    """Read real durable thread state before inspecting it."""
    return _json_object(stack.get_thread_state(thread_id), at="thread state")


def _is_active(state: dict[str, object]) -> bool:
    """Recognise a running or advancing thread before cancellation."""
    sequence = state.get("last_sequence")
    return state.get("status") == "running" or (
        isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0
    )


def _is_cancelled(state: dict[str, object]) -> bool:
    """Recognise the durable terminal cancellation state."""
    return state.get("status") == "cancelled"


def _is_completed(state: dict[str, object]) -> bool:
    """Recognise the durable completed state used for trace generation."""
    return state.get("status") == "completed"


def _wait_for_state(
    stack: ServiceStack,
    thread_id: str,
    predicate: Callable[[dict[str, object]], bool],
    *,
    timeout: float = 120.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        state = _thread_state(stack, thread_id)
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
    thread_id = _required_text(
        _json_object(created, at="created thread"), "run_id", at="created thread"
    )

    active = _wait_for_state(
        service_stack,
        thread_id,
        _is_active,
        timeout=30.0,
    )
    service_stack.record(f"cancel-active:{thread_id}", active)

    cancelling = _json_object(
        service_stack.cancel_thread(thread_id), at="cancel response"
    )
    assert _required_bool(cancelling, "cancelled", at="cancel response") is True
    assert _required_text(cancelling, "status", at="cancel response") == "cancelling"

    cancelled = _wait_for_state(
        service_stack,
        thread_id,
        _is_cancelled,
    )
    service_stack.record(f"cancelled-state:{thread_id}", cancelled)

    assert _required_text(cancelled, "status", at="cancelled thread") == "cancelled"


def test_health_and_trace_surface_are_observable(
    service_stack: ServiceStack,
    service_started_at: float,
) -> None:
    """The stack reports health and exports a real Jaeger trace."""
    health = _json_object(service_stack.health(), at="health response")
    service_stack.record("health-final", health)

    assert _required_text(health, "status", at="health response") == "ok"
    checks = _json_object(health.get("checks"), at="health checks")
    for check_name in ("database", "checkpoint", "worker"):
        check = _json_object(checks.get(check_name), at=f"health checks.{check_name}")
        assert _required_text(check, "status", at=f"health checks.{check_name}") == "ok"
    assert _required_bool(health, "worker_connected", at="health response") is True
    sqlite_fallback = _json_object(health.get("sqlite_fallback"), at="sqlite fallback")
    assert _required_bool(sqlite_fallback, "active", at="sqlite fallback") is True

    services = _json_object(service_stack.jaeger_services(), at="Jaeger services")
    service_names = set(_text_list(services.get("data"), at="Jaeger services.data"))
    assert "vaultspec-a2a" in service_names

    created = service_stack.create_thread(
        initial_message="Run a short task so worker IPC generates traceable traffic.",
        team_preset="mock-success-single",
        title="service trace probe",
    )
    thread_id = _required_text(
        _json_object(created, at="created thread"), "run_id", at="created thread"
    )
    traced_thread = _wait_for_state(
        service_stack,
        thread_id,
        _is_completed,
        timeout=60.0,
    )
    service_stack.record(f"trace-probe:{thread_id}", traced_thread)

    start_us = int(service_started_at * 1_000_000)
    found = False
    traces: dict[str, object] = {}
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        end_us = int(time.time() * 1_000_000)
        traces = _json_object(
            service_stack.jaeger_traces(
                service="vaultspec-a2a",
                start_us=start_us,
                end_us=end_us,
                limit=50,
            ),
            at="Jaeger traces",
        )
        for trace in _json_object_list(traces.get("data"), at="Jaeger traces.data"):
            processes = _json_object(
                trace.get("processes"), at="Jaeger trace processes"
            )
            trace_services = {
                service_name
                for process in processes.values()
                for service_name in [
                    _json_object(process, at="Jaeger process").get("serviceName")
                ]
                if isinstance(service_name, str)
            }
            spans = _json_object_list(trace.get("spans"), at="Jaeger trace spans")
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
