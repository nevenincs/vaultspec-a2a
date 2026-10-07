"""Acceptance lanes for the research-to-ADR document-authoring loop.

Drives :class:`vaultspec_a2a.testing.acceptance.AcceptanceHarness` across the lane
matrix and asserts that N markdown documents materialize under ``.vault/`` - this
contract's document-materialization assertion single-homed here. Three
deterministic verdict lanes run on every dispatch, each a distinct claim: AUTO
(operation-modes system approval at both gates), HUMAN (reject-with-notes ->
revision -> approve -> apply at both), and MIXED (AUTO at research, HUMAN at ADR in
ONE run, sequenced by a timed mode transition - the per-gate rather than per-run
granularity). The verdict subscriber resumes the parked run across gates.

Orthogonal to the verdict lane is the PROVIDER axis: a case names the provider it
certifies and the run-start selection is resolved from the catalog the workspace is
served, so the same MIXED contract runs under different providers. ``live-mixed``
is real Claude; ``codex`` routes the research and authoring roles to the ``codex
app-server`` provider and the inner doc-reviewer to a second lane; ``zai`` is
credential-gated - an absent ``ZAI_AUTH_TOKEN`` is a truthful skip naming the
missing credential, never a faked pass.

Infrastructure gate, not a masked failure: the test skips with a runbook pointer
when no loopback engine is reachable (resolved through the discovery contract) or
the a2a gateway is not up. Boot the stack per the runbook - a workspace-
local ``vaultspec serve --no-seat`` engine plus the a2a gateway/worker with
``VAULTSPEC_A2A_AUTHORING_SUBSCRIBER_ENABLED=true`` - then select ``-m service``.

The stack-free tests here pin the harness's own policy: the lane budgets and poll
cadence, the read-only tool allowlist, its wire readers, and its retry state
machine.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

import httpx
import pytest

from ..authoring import AuthoringTransportError
from ..control.run_start_policy import required_role_ids
from ..graph.enums import ToolKind
from ..team.team_config import load_team_config
from ..testing import settings_override
from ..testing.acceptance import (
    _ENGINE_RETRY_MAX_ATTEMPTS,
    _READ_ONLY_TOOL_KINDS,
    POLICY_AUTO,
    POLICY_HUMAN,
    PRESET_DETERMINISTIC,
    PRESET_LIVE,
    AcceptanceCase,
    AcceptanceHarness,
    ResilientAuthoringClient,
    _gateway_is_transient,
    _items,
    _poll_seconds_for,
    _retry_transient,
    is_live_lane,
    reachable_stack,
    resolve_selection,
    runtime_budget_for,
)
from ..testing.payloads import json_object

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet

    from ..authoring import AuthoringClient, AuthoringResponse
    from ..conftest import ExternalPrerequisiteRule
    from ..providers._json_contract import JsonObject

# The provider axis comes from the run-start `selection` (the whole-team lane)
# plus per-role `overrides`. Each lane makes a distinct claim: a MIXED lane runs
# two providers in one run and an ALL lane runs exactly one. The operator selects
# identifiers from the catalog currently served for the workspace.
#
# A case names only the PROVIDER it certifies, never a model: the entry, the
# native control, and its option are opaque operator-supplied values, and a lane
# whose configured selection names a different provider skips rather than
# silently certifying the wrong one.
_LANE_CODEX = "codex"
_LANE_ZAI = "zai"
_LANE_CLAUDE = "claude"

# The role a MIXED lane routes to the second (override) provider - the inner
# doc-reviewer, exactly as the retired `codex`/`zai` overlays did. Spelled as the
# worker AGENT ID because that is what `required_role_ids` yields and therefore
# the key run-start validates `overrides` against; a role-name spelling here
# would be refused as an unknown role.
_MIXED_OVERRIDE_ROLE = "vaultspec-doc-reviewer"


@dataclass(frozen=True, slots=True)
class _ResearchAdrSpec:
    """Inputs that vary across the research-to-ADR acceptance lanes."""

    label: str
    feature: str
    gate_policy: dict[str, str]
    preset: str = PRESET_DETERMINISTIC
    lane_provider: str | None = None
    requires_live_selection: bool = False
    override_roles: tuple[str, ...] = ()
    required_prerequisites: tuple[str, ...] = ()
    autonomous: bool = False


def _research_adr_case(spec: _ResearchAdrSpec) -> AcceptanceCase:
    return AcceptanceCase(
        label=spec.label,
        preset=spec.preset,
        feature=spec.feature,
        prompt=(
            "research and decide an SSE reconnection and cursor-persistence "
            "strategy for long-lived dashboard event streams"
        ),
        # Asked of the preset, never listed here. This harness mints one actor
        # token per role and run-start refuses a bundle that misses any required
        # role, so a stale list does not fail a lane's subject - it fails every
        # lane at the eligibility gate, before dispatch, with no graph ever run.
        # That is exactly what a hardcoded copy of these ids did when the preset
        # gained its plan-author role.
        roles=tuple(required_role_ids(load_team_config(spec.preset))),
        expected_doc_kinds=("research", "adr"),
        gate_policy=spec.gate_policy,
        lane_provider=spec.lane_provider,
        requires_live_selection=spec.requires_live_selection,
        override_roles=spec.override_roles,
        required_prerequisites=spec.required_prerequisites,
        autonomous=spec.autonomous,
    )


# The lane matrix. The three deterministic (Option A) lanes are the fast,
# provider-agnostic default run on every dispatch; each is a distinct claim
# (re-dispatch reference "exercise all three, not just one"), MIXED being the
# per-gate-granularity proof. The `live` case is the same MIXED shape against the
# real-Claude preset - the Option C real-provider proof - carrying `live` in its
# id so `-k "not live"` runs the fast lanes and `-k live` runs Option C alone.
CASE_AUTO = _research_adr_case(
    _ResearchAdrSpec(
        "auto", "pw7-acceptance-auto", {"research": POLICY_AUTO, "adr": POLICY_AUTO}
    )
)
CASE_HUMAN = _research_adr_case(
    _ResearchAdrSpec(
        "human",
        "pw7-acceptance-human",
        {"research": POLICY_HUMAN, "adr": POLICY_HUMAN},
    )
)
CASE_MIXED = _research_adr_case(
    _ResearchAdrSpec(
        "mixed", "pw7-acceptance-mixed", {"research": POLICY_AUTO, "adr": POLICY_HUMAN}
    )
)
CASE_LIVE_MIXED = _research_adr_case(
    _ResearchAdrSpec(
        "live-mixed",
        "pw7-acceptance-live",
        {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
        preset=PRESET_LIVE,
        lane_provider=_LANE_CLAUDE,
    )
)
# The headless-autonomous live lane: AUTO at both gates AND autonomous dispatch,
# so the worker never wires the permission-interrupt callback and a live model's
# read-only tool use (web search) proceeds unattended. This is the product's
# target headless mode; live-mixed keeps the interrupt-driven HUMAN coverage.
CASE_LIVE_AUTO = _research_adr_case(
    _ResearchAdrSpec(
        "live-auto",
        "pw7-acceptance-liveauto",
        {"research": POLICY_AUTO, "adr": POLICY_AUTO},
        preset=PRESET_LIVE,
        lane_provider=_LANE_CLAUDE,
        autonomous=True,
    )
)
# The provider-axis lanes. Both use the live preset with a mixed-provider
# profile overlay and the same MIXED gate shape as live-mixed - the same acceptance
# contract, a different provider under the authoring roles. `codex` runs live
# (file-based ChatGPT-session auth, no env token). `zai` is credential-gated: it
# skips loudly naming ZAI_AUTH_TOKEN when absent rather than faking a pass. Each
# carries its provider name in its id so `-k codex` / `-k zai` selects it alone.
CASE_CODEX = _research_adr_case(
    _ResearchAdrSpec(
        "codex",
        "pw7-acceptance-codex",
        {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
        preset=PRESET_LIVE,
        lane_provider=_LANE_CODEX,
        override_roles=(_MIXED_OVERRIDE_ROLE,),
    )
)
CASE_ZAI = _research_adr_case(
    _ResearchAdrSpec(
        "zai",
        "pw7-acceptance-zai",
        {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
        preset=PRESET_LIVE,
        lane_provider=_LANE_ZAI,
        override_roles=(_MIXED_OVERRIDE_ROLE,),
        required_prerequisites=("zai-credential",),
    )
)
# The single-provider Codex lane: every role, doc-reviewer included, routes to
# codex, so the run consumes no other provider's credential. That is what the
# mixed lanes above cannot express - each of them falls back to claude for at
# least one role - and it is witnessable with ZERO credential handling, since
# codex authenticates from its own file-based local session.
CASE_CODEX_ALL = _research_adr_case(
    _ResearchAdrSpec(
        "codex-all",
        "pw7-acceptance-codex-all",
        {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
        preset=PRESET_LIVE,
        lane_provider=_LANE_CODEX,
    )
)

_ALL_CASES = (
    CASE_AUTO,
    CASE_HUMAN,
    CASE_MIXED,
    CASE_LIVE_MIXED,
    CASE_LIVE_AUTO,
    CASE_CODEX,
    CASE_ZAI,
    CASE_CODEX_ALL,
)


def _case_param(case: AcceptanceCase) -> ParameterSet:
    """Parametrize entry that arms a real-provider (LIVE) lane with its own budget.

    The global 300s ``pytest-timeout`` is right for the fast deterministic lanes
    but far short of a LIVE lane's ~4080s budget; without an override a bare
    ``pytest -m service`` kills the live lane mid-run (between the research AUTO
    gate and the ADR HUMAN gate). ``pytest-timeout``'s per-test marker overrides
    the global for exactly the LIVE cases; the deterministic lanes keep the 300s
    global so a genuine hang there is still detected fast.
    """
    if is_live_lane(case):
        return pytest.param(
            case,
            marks=pytest.mark.timeout(runtime_budget_for(case)),
            id=case.label,
        )
    return pytest.param(case, id=case.label)


def test_live_lane_timeout_marker_matches_runtime_budget() -> None:
    """Every LIVE lane's pytest-timeout equals its runtime budget and exceeds 300s.

    A fast, stack-free guard for the exact gap that killed a bare
    ``pytest -m service -k live``: the 300s global timeout is far shorter than a
    LIVE lane's ~4080s budget, so the lane was truncated mid-run. Tied to
    :func:`runtime_budget_for` so a future budget change cannot silently re-open
    the gap. Deterministic lanes keep the 300s global (fast failure detection).
    """
    for case in _ALL_CASES:
        timeout_marks = [m for m in _case_param(case).marks if m.name == "timeout"]
        if is_live_lane(case):
            assert timeout_marks, f"LIVE lane {case.label!r} needs a timeout marker"
            armed = timeout_marks[0].args[0]
            assert armed == runtime_budget_for(case)
            assert armed > 300.0  # must exceed the global that truncated the lane
        else:
            assert not timeout_marks, (
                f"non-LIVE lane {case.label!r} must keep the 300s global timeout"
            )


def test_live_mixed_runtime_budget_is_the_specified_value() -> None:
    """The live-mixed lane budgets to (180 + AUTO 240 + HUMAN 600) x4 = 4080s."""
    assert runtime_budget_for(CASE_LIVE_MIXED) == pytest.approx(4080.0)
    # Same gate shape at the deterministic preset is x1 - well under 4080s.
    assert runtime_budget_for(CASE_MIXED) == pytest.approx(1020.0)


def test_deterministic_lanes_poll_fast_and_live_lanes_poll_slow() -> None:
    """The instant-provider deterministic lanes poll at 1s (reclaiming the ~4s/
    transition a 5s cadence wastes); the real-provider LIVE lanes keep 5s."""
    assert _poll_seconds_for(CASE_AUTO) == 1.0
    assert _poll_seconds_for(CASE_HUMAN) == 1.0
    assert _poll_seconds_for(CASE_MIXED) == 1.0
    assert _poll_seconds_for(CASE_LIVE_MIXED) == 5.0
    assert _poll_seconds_for(CASE_CODEX) == 5.0
    assert _poll_seconds_for(CASE_ZAI) == 5.0


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


# Stack-free tests of the engine client's retry state machine. They feed the
# retry loop deterministic exception sources (not a service double) to pin the
# transient-vs-terminal classification and bounded-exhaustion behaviour without a
# live engine - a pure-logic control-flow test, run in the default profile.


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


@pytest.mark.asyncio
async def test_engine_client_reresolves_bearer_once_on_401(
    tmp_path: Path,
) -> None:
    """A 401 re-resolves the bearer from discovery once, then the call succeeds.

    Uses a REAL loopback /health listener plus a real service.json so
    ``resolve_engine`` genuinely resolves the fresh bearer - no doubles. This
    is the one retry path the other tests cannot reach (it needs a resolvable
    engine), pinning that the ``before_retry`` hook actually rotates the
    credential and retries immediately.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        @override
        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    service_json = tmp_path / "service.json"
    service_json.write_text(
        json.dumps(
            {
                "port": server.server_address[1],
                "service_token": "rotated-tok",
                "pid": os.getpid(),
                "last_heartbeat": int(time.time() * 1000),
            }
        ),
        encoding="utf-8",
    )
    calls = 0
    try:

        async def denied_once(_self: AuthoringClient) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise AuthoringTransportError(
                    status_code=401,
                    message="machine bearer expired",
                    error_kind="authoring_unauthorized",
                )
            return "ok"

        client = ResilientAuthoringClient("http://127.0.0.1:1", "stale-tok")
        with settings_override(engine_service_json=service_json):
            async with client:
                result = await client._call_resilient(
                    lambda: denied_once(client), operation="denied_once"
                )
        assert result == "ok"
        assert calls == 2  # 401 consumed one attempt, immediate retry
        assert client._bearer_token == "rotated-tok"  # rotation really ran
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


# The gateway status poll rides the same shared retry loop; these pin its
# transient-vs-terminal classification and the loop's behaviour through the
# gateway classifier with deterministic exception sources (pure control flow,
# no service double) - the same device as the engine-client tests above.


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


@pytest.mark.service
@pytest.mark.resource("loopback-stack")
@pytest.mark.asyncio
@pytest.mark.parametrize("case", [_case_param(c) for c in _ALL_CASES])
async def test_pw7_research_adr_materializes_two_documents(
    case: AcceptanceCase,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """The research_adr loop materializes exactly the expected document set.

    Drives the standing acceptance case end to end and asserts a research and
    an ADR document materialize under the engine workspace ``.vault/`` - the
    document-materialization contract for ``research_adr`` (N = 2) - across the
    three verdict lanes (HUMAN reject-with-notes -> revision -> approve; AUTO
    operation-modes system approval; MIXED per-gate). Verdicts are driven
    programmatically over the engine surface.
    """
    for prerequisite_id in case.required_prerequisites:
        external_prerequisite(prerequisite_id, f"the {case.label} lane needs it")
    stack = reachable_stack()
    if stack is None:
        external_prerequisite.absent("loopback-stack")
    gateway_url, engine_base_url, engine_bearer, vault_root = stack
    selection, overrides = await resolve_selection(
        case, gateway_url, str(vault_root.parent), external_prerequisite
    )
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
        gateway_url=gateway_url,
        selection=selection,
        overrides=overrides,
    )

    gates_driven = await harness.run()

    assert gates_driven == list(case.expected_doc_kinds)
    assert len(harness.materializations) == len(case.expected_doc_kinds)
    materialized = harness.materialized()
    for kind in case.expected_doc_kinds:
        assert materialized[kind], (
            f"no {kind} document materialized on disk for {case.label}"
        )
    # Every human-gate apply receipt names a real materialized path on disk.
    for record in harness.materializations:
        if record.document_path is not None:
            assert Path(record.document_path).name, (
                "apply receipt carried an empty document path"
            )
