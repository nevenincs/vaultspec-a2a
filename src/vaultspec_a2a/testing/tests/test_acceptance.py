"""The acceptance harness's own policy, checked without a stack.

Pins the lane budgets and poll cadence, the read-only tool allowlist, the wire
readers, and the retry state machine. The retry tests feed the loop deterministic
exception sources to fix the transient-vs-terminal classification and the
bounded-exhaustion behaviour without a live engine - pure control flow, run in
the default profile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from ...authoring import AuthoringTransportError
from ...graph.enums import ToolKind
from ..acceptance import (
    _ENGINE_RETRY_MAX_ATTEMPTS,
    _READ_ONLY_TOOL_KINDS,
    POLICY_AUTO,
    POLICY_HUMAN,
    PRESET_DETERMINISTIC,
    PRESET_LIVE,
    AcceptanceCase,
    ResilientAuthoringClient,
    _gateway_is_transient,
    _items,
    _poll_seconds_for,
    _retry_transient,
    runtime_budget_for,
)
from ..payloads import json_object

if TYPE_CHECKING:
    from ...authoring import AuthoringClient, AuthoringResponse
    from ...providers._json_contract import JsonObject

_GATES_AUTO = {"research": POLICY_AUTO, "adr": POLICY_AUTO}
_GATES_HUMAN = {"research": POLICY_HUMAN, "adr": POLICY_HUMAN}
_GATES_MIXED = {"research": POLICY_AUTO, "adr": POLICY_HUMAN}


def _case(preset: str, gate_policy: dict[str, str]) -> AcceptanceCase:
    return AcceptanceCase(
        label="policy-probe",
        preset=preset,
        feature="acceptance-policy-probe",
        prompt="probe the lane policy",
        roles=(),
        expected_doc_kinds=tuple(gate_policy),
        gate_policy=gate_policy,
    )


def test_live_mixed_runtime_budget_is_the_specified_value() -> None:
    """The live-mixed lane budgets to (180 + AUTO 240 + HUMAN 600) x4 = 4080s."""
    assert runtime_budget_for(_case(PRESET_LIVE, _GATES_MIXED)) == pytest.approx(4080.0)
    # Same gate shape at the deterministic preset is x1 - well under 4080s.
    assert runtime_budget_for(
        _case(PRESET_DETERMINISTIC, _GATES_MIXED)
    ) == pytest.approx(1020.0)


def test_deterministic_lanes_poll_fast_and_live_lanes_poll_slow() -> None:
    """The instant-provider deterministic lanes poll at 1s (reclaiming the ~4s/
    transition a 5s cadence wastes); the real-provider LIVE lanes keep 5s."""
    for gates in (_GATES_AUTO, _GATES_HUMAN, _GATES_MIXED):
        assert _poll_seconds_for(_case(PRESET_DETERMINISTIC, gates)) == 1.0
        assert _poll_seconds_for(_case(PRESET_LIVE, gates)) == 5.0


def test_read_only_tool_kinds_are_allowlisted_and_writes_are_not() -> None:
    """Read-only research tool kinds are allow-listed; write/execute kinds are not -
    membership holds on the raw string value the engine tags each permission with."""
    for allowed in (ToolKind.READ, ToolKind.SEARCH, ToolKind.FETCH, ToolKind.THINK):
        assert allowed in _READ_ONLY_TOOL_KINDS
    for denied in (ToolKind.EDIT, ToolKind.DELETE, ToolKind.MOVE, ToolKind.EXECUTE):
        assert denied not in _READ_ONLY_TOOL_KINDS
    assert "search" in _READ_ONLY_TOOL_KINDS
    assert "edit" not in _READ_ONLY_TOOL_KINDS


def test_json_reader_rejects_a_non_object_gateway_response() -> None:
    """A gateway response array cannot silently enter the polling state machine."""
    with pytest.raises(AssertionError, match="gateway run-status response"):
        json_object(["not a run status"], at="gateway run-status response")


def test_items_reader_rejects_a_malformed_review_queue_item_list() -> None:
    """A present queue ``items`` field must contain objects, never scalars."""
    with pytest.raises(AssertionError, match=r"review-queue response\.items"):
        _items({"items": ["not a review item"]}, at="review-queue response")


def test_json_reader_rejects_a_malformed_apply_receipt() -> None:
    """A successful apply response still requires an object receipt boundary."""
    apply_response = json_object(
        {"receipt": ["not an apply receipt"]}, at="research apply response"
    )
    with pytest.raises(AssertionError, match="research apply receipt"):
        json_object(apply_response.get("receipt"), at="research apply receipt")


def test_json_reader_rejects_a_malformed_permission_history_state() -> None:
    """History must contain an object state before permission polling may continue."""
    history = json_object(
        {"state": ["not a permission state"]}, at="gateway history response"
    )
    with pytest.raises(AssertionError, match="gateway history state"):
        json_object(history.get("state"), at="gateway history state")


@pytest.mark.asyncio
async def test_engine_client_retries_transient_then_succeeds() -> None:
    """A transient read timeout is retried with backoff and then succeeds."""
    calls = 0

    async def flaky(_self: AuthoringClient, value: str) -> str:
        nonlocal calls
        calls += 1
        if calls < _ENGINE_RETRY_MAX_ATTEMPTS:
            raise httpx.ReadTimeout("engine stalled")
        return value

    client = ResilientAuthoringClient("http://127.0.0.1:1", "tok")
    async with client:
        result = await client._call_resilient(
            lambda: flaky(client, "ok"), operation="flaky"
        )
    assert result == "ok"
    # First attempt + (max_attempts - 1) transient retries, all inside budget.
    assert calls == _ENGINE_RETRY_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_engine_client_does_not_retry_terminal_4xx() -> None:
    """A non-401 4xx is terminal - re-raised on the first attempt, never retried."""
    calls = 0

    async def denied(_self: AuthoringClient) -> AuthoringResponse:
        nonlocal calls
        calls += 1
        raise AuthoringTransportError(
            status_code=409,
            message="stale review",
            error_kind="authoring_stale_review",
        )

    client = ResilientAuthoringClient("http://127.0.0.1:1", "tok")
    async with client:
        with pytest.raises(AuthoringTransportError) as excinfo:
            await client._call_resilient(lambda: denied(client), operation="denied")
    assert excinfo.value.status_code == 409
    assert calls == 1


@pytest.mark.asyncio
async def test_engine_client_fails_loud_on_transient_exhaustion() -> None:
    """Transient failures beyond max_attempts fail loud, never silently hang."""
    calls = 0

    async def always_stalls(_self: AuthoringClient) -> AuthoringResponse:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("all connection attempts failed")

    client = ResilientAuthoringClient("http://127.0.0.1:1", "tok")
    async with client:
        with pytest.raises(AssertionError) as excinfo:
            await client._call_resilient(
                lambda: always_stalls(client), operation="always_stalls"
            )
    assert calls == _ENGINE_RETRY_MAX_ATTEMPTS
    assert "transient class exhausted" in str(excinfo.value)


# The gateway status poll rides the same shared retry loop; these pin its
# transient-vs-terminal classification and the loop's behaviour through the
# gateway classifier with deterministic exception sources, the same device as
# the engine-client tests above.


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """A real ``HTTPStatusError`` as ``raise_for_status`` would raise it."""
    request = httpx.Request("GET", "http://127.0.0.1:1/v1/runs/pw7-test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"status {status_code}", request=request, response=response
    )


@pytest.mark.asyncio
async def test_gateway_poll_retries_dropped_connection_then_succeeds() -> None:
    """A dropped connection then a read timeout are absorbed; the poll succeeds."""
    calls = 0
    transients: list[Exception] = [
        httpx.RemoteProtocolError("server disconnected"),
        httpx.ReadTimeout("gateway stalled"),
    ]

    async def flaky() -> JsonObject:
        nonlocal calls
        calls += 1
        if transients:
            raise transients.pop(0)
        return {"status": "running"}

    result = await _retry_transient(
        flaky, name="gateway status poll 'pw7-test'", is_transient=_gateway_is_transient
    )
    assert result == {"status": "running"}
    assert calls == _ENGINE_RETRY_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_gateway_poll_does_not_retry_terminal_4xx() -> None:
    """A 4xx from the gateway is a real denial/routing error - never retried."""
    calls = 0

    async def not_found() -> JsonObject:
        nonlocal calls
        calls += 1
        raise _http_status_error(404)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await _retry_transient(
            not_found,
            name="gateway status poll 'pw7-test'",
            is_transient=_gateway_is_transient,
        )
    assert excinfo.value.response.status_code == 404
    assert calls == 1


@pytest.mark.asyncio
async def test_gateway_poll_retries_5xx_and_fails_loud_on_exhaustion() -> None:
    """5xx is transient; persistent 5xx exhausts the budget and fails loud."""
    calls = 0

    async def always_500() -> JsonObject:
        nonlocal calls
        calls += 1
        raise _http_status_error(500)

    with pytest.raises(AssertionError) as excinfo:
        await _retry_transient(
            always_500,
            name="gateway status poll 'pw7-test'",
            is_transient=_gateway_is_transient,
        )
    assert calls == _ENGINE_RETRY_MAX_ATTEMPTS
    assert "gateway status poll" in str(excinfo.value)
    assert "transient class exhausted" in str(excinfo.value)
