"""Headless acceptance harness for the document-authoring loop.

The STANDING acceptance driver for the research-to-ADR phase machine, built as a
reusable, parameterized harness rather than a one-off so the successor document
workloads (curation, plan-authoring) reuse it. Given a prompt it drives one run
end to end against the live loopback stack and asserts that N markdown documents
materialize under ``.vault/`` - this contract's document-materialization
assertion single-homed here.

The loop it exercises, all live and mock-free, across three verdict lanes:

* mint one Agent-kind actor token per preset role plus a human-class reviewer
  token (also the operation-mode policy setter) against the engine authoring API;
* assert the hardened v1 ``run-start`` refusals (422: missing target feature;
  422: an actor-token bundle not covering every required role);
* ``run-start`` the preset with the token bundle and a target feature;
* drive each gate's verdict per its per-gate policy PROGRAMMATICALLY over the
  engine surface:
  - **HUMAN** gate: reject-with-notes first (``decision=edit`` == request-changes,
    which returns the changeset to Draft and stales the approval), assert the run
    re-authors and re-submits (the revision loop, not a dead end), then approve and
    apply, asserting the materialization receipt;
  - **AUTO** gate: set the worktree operation mode to ``autonomous`` BEFORE the
    gate's submit, so the engine's ``submit_for_review`` system-auto-approves under
    the ``system:operation-modes`` actor (recording a ``SystemPolicyApprovalRecord``,
    a record class DISTINCT from a human ``ReviewDecisionRecord``) and auto-applies.
    The harness asserts that system marker, never a human decision - the ADR's own
    anti-bypass invariant, not merely "the run completed fast";
* MIXED = a genuinely different policy per gate in ONE run (AUTO at research, HUMAN
  at ADR), sequenced by a timed mode transition, proving the per-gate (not per-run)
  granularity the ADR promises;
* the verdict subscriber resumes the parked run across gates;
* assert the expected documents materialized on disk with the expected stems.

Orthogonal to the verdict lane is the PROVIDER axis: a case selects a model
profile at run-start, so the same MIXED contract
runs under different providers. ``live-mixed`` is real Claude; ``codex`` overlays a
mixed codex/claude profile (the research and authoring roles on the ``codex
app-server`` provider, the inner doc-reviewer on Claude); ``zai`` overlays a Z.ai
profile and is credential-gated - an absent ``ZAI_AUTH_TOKEN`` is a truthful skip
naming the missing credential, never a faked pass.

Gate detection keys on the ENGINE surface (a queued proposal / an applied-under-
policy marker scoped to this run's changeset id ``cs:<run_id>:<phase>-r<cycle>``),
not the a2a semantic phase, so it is robust to the reconciler masking the semantic
phase after a subscriber resume.

Wire shapes are grounded in the engine Rust source (read-only), not this brief's
prose: ``ReviewDecisionRequest`` (``decision`` enum ``approve|reject|edit|respond``,
load-bearing ``reviewed_revision``), ``ApplyRequest`` (``changeset_id`` +
``approval_id``), ``SetOperationModeRequest`` (``mode`` enum
``manual|assisted|autonomous``, human/system actor only), the apply receipt's
``child.{document_path,result_stem,outcome}``, and the ``applied_under_policy``
projection lane carrying ``system_actor`` / ``mode`` / ``policy_id``.

Infrastructure gate, not a masked failure: the test skips with a runbook pointer
when no loopback engine is reachable (resolved through the discovery contract) or
the a2a gateway is not up. Boot the stack per the runbook - a workspace-
local ``vaultspec serve --no-seat`` engine plus the a2a gateway/worker with
``VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true`` - then select ``-m service``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from _pytest.mark.structures import ParameterSet

from ..authoring import AuthoringClient, mint_actor_token
from ..authoring._envelope import AuthoringResponse, Denial
from ..authoring._errors import AuthoringTransportError
from ..authoring.discovery import SERVICE_JSON_ENV, resolve_engine

_GATEWAY_URL = os.environ.get("VAULTSPEC_GATEWAY_URL", "http://127.0.0.1:18100")
_RESEARCH_ADR_ROLES = (
    "vaultspec-researcher",
    "vaultspec-synthesist",
    "vaultspec-adr-author",
    "vaultspec-doc-reviewer",
)

# Per-gate verdict policies (the lane axis).
POLICY_AUTO = "AUTO"
POLICY_HUMAN = "HUMAN"

# Operation-mode wire values (engine `OperationMode`, snake_case).
_MODE_MANUAL = "manual"
_MODE_AUTONOMOUS = "autonomous"

# Review-decision wire values (engine `ReviewDecisionKind`, snake_case). `edit`
# is the request-changes / reject-with-notes device: it returns the changeset to
# Draft and stales the approval, routing the a2a run back to the phase writer.
_DECISION_APPROVE = "approve"
_DECISION_EDIT = "edit"

# The command-envelope discriminator (engine `CommandKind`) the
# `/v1/reviews/{approval_id}/decisions` route requires, keyed by the decision.
# The envelope command must be a real CommandKind the reviewer is authorized for
# (the `ResolvedCommand` extractor deserializes it and runs `run_authorization`
# on it, engine `http/mod.rs:283`); the engine maps `ApprovalDecision` →
# `CommandKind` as Approve→`approve`, Reject→`reject`, RequestChanges(edit)→
# `edit_proposal`. There is NO `submit_review_decision` CommandKind — that is the
# handler fn name, not a wire command (posting it fails 400 unknown-variant).
_DECISION_COMMAND: dict[str, str] = {
    _DECISION_APPROVE: "approve",
    _DECISION_EDIT: "edit_proposal",
    "reject": "reject",
}

# The system auto-approval actor id + policy id the operation-modes machinery
# stamps on a `SystemPolicyApprovalRecord` (engine `modes.rs`
# `SYSTEM_AUTO_APPROVER_ID` / `MODE_POLICY_ID`). The AUTO lane asserts these
# exactly - the anti-bypass invariant - never a human decision record.
_SYSTEM_AUTO_APPROVER_ID = "system:operation-modes"
_MODE_POLICY_ID = "authoring.operation_modes"

# The two research_adr driver presets. DETERMINISTIC is the in-process
# Provider.DETERMINISTIC device: the fast, provider-agnostic Option A lane run
# on every dispatch. LIVE is the real-Claude preset: the Option C real-provider
# proof, run once after the Option A lanes are green, select it with `-k live`.
_PRESET_DETERMINISTIC = "vaultspec-adr-research-deterministic"
_PRESET_LIVE = "vaultspec-adr-research"

# Provider-axis profiles overlaid on the live preset. `codex` routes the
# three research/authoring roles to the codex
# app-server provider (doc-reviewer stays claude); `zai` routes them to Z.ai. The
# Z.ai lane is credential-gated - the env var the harness skips on when absent.
_PROFILE_CODEX = "codex"
_PROFILE_ZAI = "zai"
_ZAI_CREDENTIAL_ENV = "ZAI_AUTH_TOKEN"


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    """A parameterized acceptance case.

    Parameters
    ----------
    label:             A short, stable id for the parametrization.
    preset:            The document-authoring team preset to run.
    feature:           The target feature tag the documents are authored for.
    prompt:            The run's opening research prompt.
    roles:             The preset's required role ids (the token bundle keys).
    expected_doc_kinds:
        The ``.vault`` subdirectories a materialized document is expected under,
        in gate order (e.g. ``("research", "adr")``).
    gate_policy:       Per-gate verdict policy - :data:`POLICY_AUTO` (system
                       operation-modes auto-approval) or :data:`POLICY_HUMAN`
                       (human reject-with-notes -> revision -> approve -> apply) -
                       keyed by gate ordinal name, in gate order.
    profile_id:        The model profile selected at run-start (the provider axis).
                       ``team-defaults`` (the implicit empty overlay) keeps the
                       preset's own per-role providers; a named profile
                       (e.g. ``codex``) overlays per-role providers on top, so one
                       preset drives several provider lanes.
    required_env:      Environment variables that MUST be present for the lane to
                       run. A missing one is an honest skip-with-reason naming the
                       variable (a credential-gated lane), never a faked pass.
    """

    label: str
    preset: str
    feature: str
    prompt: str
    roles: tuple[str, ...]
    expected_doc_kinds: tuple[str, ...]
    gate_policy: dict[str, str] = field(default_factory=dict)
    profile_id: str = "team-defaults"
    required_env: tuple[str, ...] = ()


def _research_adr_case(
    label: str,
    feature: str,
    gate_policy: dict[str, str],
    *,
    preset: str = _PRESET_DETERMINISTIC,
    profile_id: str = "team-defaults",
    required_env: tuple[str, ...] = (),
) -> AcceptanceCase:
    return AcceptanceCase(
        label=label,
        preset=preset,
        feature=feature,
        prompt=(
            "research and decide an SSE reconnection and cursor-persistence "
            "strategy for long-lived dashboard event streams"
        ),
        roles=_RESEARCH_ADR_ROLES,
        expected_doc_kinds=("research", "adr"),
        gate_policy=gate_policy,
        profile_id=profile_id,
        required_env=required_env,
    )


# The lane matrix. The three deterministic (Option A) lanes are the fast,
# provider-agnostic default run on every dispatch; each is a distinct claim
# (re-dispatch reference "exercise all three, not just one"), MIXED being the
# per-gate-granularity proof. The `live` case is the same MIXED shape against the
# real-Claude preset - the Option C real-provider proof - carrying `live` in its
# id so `-k "not live"` runs the fast lanes and `-k live` runs Option C alone.
CASE_AUTO = _research_adr_case(
    "auto", "pw7-acceptance-auto", {"research": POLICY_AUTO, "adr": POLICY_AUTO}
)
CASE_HUMAN = _research_adr_case(
    "human", "pw7-acceptance-human", {"research": POLICY_HUMAN, "adr": POLICY_HUMAN}
)
CASE_MIXED = _research_adr_case(
    "mixed", "pw7-acceptance-mixed", {"research": POLICY_AUTO, "adr": POLICY_HUMAN}
)
CASE_LIVE_MIXED = _research_adr_case(
    "live-mixed",
    "pw7-acceptance-live",
    {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
    preset=_PRESET_LIVE,
)
# The provider-axis lanes. Both use the live preset with a mixed-provider
# profile overlay and the same MIXED gate shape as live-mixed - the same acceptance
# contract, a different provider under the authoring roles. `codex` runs live
# (file-based ChatGPT-session auth, no env token). `zai` is credential-gated: it
# skips loudly naming ZAI_AUTH_TOKEN when absent rather than faking a pass. Each
# carries its provider name in its id so `-k codex` / `-k zai` selects it alone.
CASE_CODEX = _research_adr_case(
    "codex",
    "pw7-acceptance-codex",
    {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
    preset=_PRESET_LIVE,
    profile_id=_PROFILE_CODEX,
)
CASE_ZAI = _research_adr_case(
    "zai",
    "pw7-acceptance-zai",
    {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
    preset=_PRESET_LIVE,
    profile_id=_PROFILE_ZAI,
    required_env=(_ZAI_CREDENTIAL_ENV,),
)

_ALL_CASES = (CASE_AUTO, CASE_HUMAN, CASE_MIXED, CASE_LIVE_MIXED, CASE_CODEX, CASE_ZAI)


def _runtime_budget_for(case: AcceptanceCase) -> float:
    """The per-lane deadline scaled to gate count/policy, not one global default.

    A HUMAN gate runs a full reject-with-notes revision loop (park -> edit ->
    re-author -> re-submit -> approve -> apply); an AUTO gate resolves in one
    synchronous submit; the LIVE preset authors each turn with a real provider
    (minutes/turn), so it multiplies. This is the SINGLE source of truth for both
    the harness's own deadline and the per-case ``pytest-timeout`` marker, so the
    two can never drift - a bare ``pytest -m service -k live`` must not be killed
    by the 300s global before the lane's own specified workload completes.
    """
    per_gate = {POLICY_HUMAN: 600.0, POLICY_AUTO: 240.0}
    base = 180.0
    budget = base + sum(per_gate.get(p, 300.0) for p in case.gate_policy.values())
    return budget * (4.0 if case.preset == _PRESET_LIVE else 1.0)


def _case_param(case: AcceptanceCase) -> ParameterSet:
    """Parametrize entry that arms a real-provider (LIVE) lane with its own budget.

    The global 300s ``pytest-timeout`` is right for the fast deterministic lanes
    but far short of a LIVE lane's ~4080s budget; without an override a bare
    ``pytest -m service`` kills the live lane mid-run (between the research AUTO
    gate and the ADR HUMAN gate). ``pytest-timeout``'s per-test marker overrides
    the global for exactly the LIVE cases; the deterministic lanes keep the 300s
    global so a genuine hang there is still detected fast.
    """
    if case.preset == _PRESET_LIVE:
        return pytest.param(
            case,
            marks=pytest.mark.timeout(_runtime_budget_for(case)),
            id=case.label,
        )
    return pytest.param(case, id=case.label)


def test_live_lane_timeout_marker_matches_runtime_budget() -> None:
    """Every LIVE lane's pytest-timeout equals its runtime budget and exceeds 300s.

    A fast, stack-free guard for the exact gap that killed a bare
    ``pytest -m service -k live``: the 300s global timeout is far shorter than a
    LIVE lane's ~4080s budget, so the lane was truncated mid-run. Tied to
    :func:`_runtime_budget_for` so a future budget change cannot silently re-open
    the gap. Deterministic lanes keep the 300s global (fast failure detection).
    """
    for case in _ALL_CASES:
        timeout_marks = [m for m in _case_param(case).marks if m.name == "timeout"]
        if case.preset == _PRESET_LIVE:
            assert timeout_marks, f"LIVE lane {case.label!r} needs a timeout marker"
            armed = timeout_marks[0].args[0]
            assert armed == _runtime_budget_for(case)
            assert armed > 300.0  # must exceed the global that truncated the lane
        else:
            assert not timeout_marks, (
                f"non-LIVE lane {case.label!r} must keep the 300s global timeout"
            )


def test_live_mixed_runtime_budget_is_the_specified_value() -> None:
    """The live-mixed lane budgets to (180 + AUTO 240 + HUMAN 600) x4 = 4080s."""
    assert _runtime_budget_for(CASE_LIVE_MIXED) == pytest.approx(4080.0)
    # Same gate shape at the deterministic preset is x1 - well under 4080s.
    assert _runtime_budget_for(CASE_MIXED) == pytest.approx(1020.0)


def _dig(item: dict, field_name: str) -> str | None:
    """Return the first string value for *field_name* nested anywhere in *item*."""
    value = item.get(field_name)
    if isinstance(value, str):
        return value
    for nested in item.values():
        if isinstance(nested, dict):
            found = _dig(nested, field_name)
            if found:
                return found
    return None


def _items(data: object) -> list[dict]:
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


@dataclass(slots=True)
class Materialization:
    """One materialized document's evidence, per gate."""

    gate: str
    source: str  # "auto" | "human"
    changeset_id: str
    document_path: str | None = None
    result_stem: str | None = None


# Standard-practice transient-retry policy for BOTH harness clients - the engine
# authoring client and the gateway status polls - mirroring LangGraph's
# RetryPolicy shape
# (docs.langchain.com/oss/python/langgraph/fault-tolerance#retries) and the
# transient-error taxonomy in thinking-in-langgraph (network/timeout/5xx are the
# canonical transient class, retried with exponential backoff + jitter; a 4xx is
# terminal and never retried). ``max_attempts`` counts the first try. The loop
# itself lives in exactly one place, :func:`_retry_transient`; the per-client
# pieces are only the transient-vs-terminal classifiers.
_ENGINE_RETRY_MAX_ATTEMPTS = 3
_ENGINE_RETRY_INITIAL_INTERVAL = 0.5
_ENGINE_RETRY_BACKOFF_FACTOR = 2.0
_ENGINE_RETRY_MAX_INTERVAL = 8.0
# Per-attempt cap - the ``TimeoutPolicy``/``timeout=`` companion to a retry policy
# (same docs) - so a hung socket fails fast into the next attempt instead of
# stalling the whole poll on one dead read.
_ENGINE_RETRY_PER_ATTEMPT_TIMEOUT = 20.0


async def _retry_transient(
    op: Callable[[], Awaitable[Any]],
    *,
    name: str,
    is_transient: Callable[[BaseException], bool],
    before_retry: Callable[[BaseException], Awaitable[bool]] | None = None,
) -> Any:
    """Run ``op`` under the harness's bounded transient-retry policy.

    The single home of the retry loop for both harness clients. A failure that
    ``before_retry`` consumes (returns ``True``) retries immediately with no
    backoff and no attempt-classification - the credential-rotation hook. A
    failure ``is_transient`` accepts is retried with exponential backoff +
    jitter up to ``_ENGINE_RETRY_MAX_ATTEMPTS``; anything else re-raises
    immediately as terminal. Exhaustion fails loud rather than hanging.
    """
    interval = _ENGINE_RETRY_INITIAL_INTERVAL
    last_exc: BaseException | None = None
    for attempt in range(1, _ENGINE_RETRY_MAX_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(op(), _ENGINE_RETRY_PER_ATTEMPT_TIMEOUT)
        except Exception as exc:
            if before_retry is not None and await before_retry(exc):
                continue  # consumed (e.g. one-shot bearer refresh) - retry now
            if not is_transient(exc):
                raise  # terminal class - never retried
            last_exc = exc
        if attempt < _ENGINE_RETRY_MAX_ATTEMPTS:
            await asyncio.sleep(interval + random.uniform(0.0, interval))
            interval = min(
                interval * _ENGINE_RETRY_BACKOFF_FACTOR, _ENGINE_RETRY_MAX_INTERVAL
            )
    raise AssertionError(
        f"{name} failed after "
        f"{_ENGINE_RETRY_MAX_ATTEMPTS} attempts (transient class exhausted)"
    ) from last_exc


def _gateway_is_transient(exc: BaseException) -> bool:
    """The gateway status-poll transient classifier: network/timeout/5xx only.

    A 4xx from the gateway (``raise_for_status`` -> ``httpx.HTTPStatusError``)
    is a real denial/identity/routing error and must surface immediately; a
    dropped connection (``httpx.TransportError`` covers ``RemoteProtocolError``
    and read/connect timeouts), the per-attempt ``TimeoutError`` cap, or a 5xx
    are the textbook transient class a 5s poll loop must absorb.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, TimeoutError))


class _ResilientAuthoringClient(AuthoringClient):
    """An :class:`AuthoringClient` hardened for a long real-provider lane.

    Two standard fault-tolerance mechanisms compose on every engine call:

    * **Machine-bearer re-resolution on an outer-gate 401.** A shared engine can
      restart mid-run - a real observed failure: a long real-provider run
      outlives one engine process, so the bearer cached at start goes stale and
      the next call 401s (outer bearer-gate: status 401, no ``error_kind``). On
      that 401 the endpoint is re-resolved from the workspace ``service.json``
      (the engine mints a fresh bearer at each boot and republishes it there),
      the new bearer + transport are swapped in, and the call retried. This is
      the standard credential-refresh-then-retry token-rotation pattern.
    * **Bounded transient retry with backoff + per-attempt timeout.** A read
      timeout / connect error / 5xx on the harness's own poll of a shared,
      concurrently-loaded engine is a textbook transient failure, not a defect;
      the standard response is a bounded retry with exponential backoff, retrying
      ONLY transient classes and never a 4xx, failing loud on exhaustion. Shape
      and taxonomy follow LangGraph's ``RetryPolicy`` / ``TimeoutPolicy``
      (docs.langchain.com/oss/python/langgraph/fault-tolerance) and the
      transient-error row of thinking-in-langgraph's error taxonomy.

    Being a subclass, it is a drop-in wherever an ``AuthoringClient`` is expected.
    """

    async def _reresolve_bearer(self) -> None:
        endpoint = resolve_engine()
        if endpoint is None:
            raise AssertionError(
                "engine unreachable while re-resolving the bearer after a 401 "
                "(engine likely restarted and its service.json is not fresh)"
            )
        self._base_url = endpoint.base_url.rstrip("/")
        self._bearer_token = endpoint.bearer_token
        await self._client.aclose()
        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=httpx.Timeout(30.0, connect=5.0)
        )

    async def _call_resilient(
        self, method: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        """Invoke a base-class call under bearer-refresh + bounded transient retry.

        A 401 triggers a single bearer re-resolve then an immediate retry (no
        backoff - a credential rotation, not congestion). A transient transport
        failure (``httpx.TransportError`` - read/connect timeouts and network
        errors - or the per-attempt ``TimeoutError``) or a 5xx is retried with
        exponential backoff + jitter up to ``max_attempts``. Any other 4xx is a
        terminal identity/denial error, re-raised immediately. Exhaustion fails
        loud rather than returning a partial or hanging. The loop itself is the
        shared :func:`_retry_transient`; only the classification is engine-side.
        """
        reresolved = False

        async def before_retry(exc: BaseException) -> bool:
            nonlocal reresolved
            if (
                isinstance(exc, AuthoringTransportError)
                and exc.status_code == 401
                and not reresolved
            ):
                await self._reresolve_bearer()
                reresolved = True
                return True  # immediate retry on the fresh bearer, no backoff
            return False

        def is_transient(exc: BaseException) -> bool:
            if isinstance(exc, AuthoringTransportError):
                return exc.status_code >= 500  # 5xx transient; other 4xx terminal
            return isinstance(exc, (httpx.TransportError, TimeoutError))

        return await _retry_transient(
            lambda: method(self, *args, **kwargs),
            name=f"engine call {getattr(method, '__name__', method)!r}",
            is_transient=is_transient,
            before_retry=before_retry,
        )

    async def get(self, *args: Any, **kwargs: Any) -> AuthoringResponse:
        return await self._call_resilient(AuthoringClient.get, *args, **kwargs)

    async def post_command(
        self, *args: Any, **kwargs: Any
    ) -> AuthoringResponse | Denial:
        return await self._call_resilient(AuthoringClient.post_command, *args, **kwargs)

    async def post_bare(self, *args: Any, **kwargs: Any) -> AuthoringResponse | Denial:
        return await self._call_resilient(AuthoringClient.post_bare, *args, **kwargs)


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

    client = _ResilientAuthoringClient("http://127.0.0.1:1", "tok")
    async with client:
        result = await client._call_resilient(flaky, "ok")
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

    client = _ResilientAuthoringClient("http://127.0.0.1:1", "tok")
    async with client:
        with pytest.raises(AuthoringTransportError) as excinfo:
            await client._call_resilient(denied)
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

    client = _ResilientAuthoringClient("http://127.0.0.1:1", "tok")
    async with client:
        with pytest.raises(AssertionError) as excinfo:
            await client._call_resilient(always_stalls)
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

        def log_message(self, format: str, *args: Any) -> None:
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
    prior = os.environ.get(SERVICE_JSON_ENV)
    os.environ[SERVICE_JSON_ENV] = str(service_json)
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

        client = _ResilientAuthoringClient("http://127.0.0.1:1", "stale-tok")
        async with client:
            result = await client._call_resilient(denied_once)
            assert result == "ok"
            assert calls == 2  # 401 consumed one attempt, immediate retry
            assert client._bearer_token == "rotated-tok"  # rotation really ran
    finally:
        if prior is None:
            os.environ.pop(SERVICE_JSON_ENV, None)
        else:
            os.environ[SERVICE_JSON_ENV] = prior
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

    async def flaky() -> dict:
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

    async def not_found() -> dict:
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

    async def always_500() -> dict:
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


@dataclass(slots=True)
class AcceptanceHarness:
    """Drives one acceptance case against the live loopback stack."""

    case: AcceptanceCase
    engine_base_url: str
    engine_bearer: str
    vault_root: Path
    gateway_url: str = _GATEWAY_URL
    run_id: str = field(default_factory=lambda: f"pw7-{int(time.time())}")
    phases_seen: list[str] = field(default_factory=list)
    materializations: list[Materialization] = field(default_factory=list)
    feature: str = ""
    _idk_counter: itertools.count = field(default_factory=lambda: itertools.count())
    _current_mode: str | None = None

    def __post_init__(self) -> None:
        # A UNIQUE per-run feature tag: the engine's create refuses to overwrite an
        # existing document at the predicted path (path-collision gate), so a fixed
        # per-lane tag makes a re-run's apply fail on the prior run's leftover doc.
        # Deriving it from the run id keeps it unique AND identifiable/disposable in
        # the shared engine vault (pw7-acceptance-<lane>-<run-stamp>).
        if not self.feature:
            self.feature = f"{self.case.feature}-{self.run_id.rsplit('-', 1)[-1]}"

    def _idk(self, tag: str) -> str:
        """A grammar-valid, unique-per-call idempotency key for this run."""
        return f"idk-{tag}-{self.run_id}-{next(self._idk_counter)}"

    # ------------------------------------------------------------------
    # Token + run-start
    # ------------------------------------------------------------------

    async def _mint(self, ec: AuthoringClient, actor_id: str, kind: str) -> str:
        minted = await mint_actor_token(ec, actor_id=actor_id, kind=kind)
        assert isinstance(minted, AuthoringResponse), f"mint denied: {minted}"
        token = minted.data.get("raw_token")
        assert isinstance(token, str) and token
        return token

    async def _run_start(
        self,
        hc: httpx.AsyncClient,
        *,
        run_id: str,
        tokens: dict[str, str],
        feature: str | None,
        expect: int,
    ) -> httpx.Response:
        meta: dict = {"workspace_root": str(self.vault_root.parent), "nickname": run_id}
        if feature is not None:
            meta["feature_tag"] = feature
        body: dict = {
            "team_preset": self.case.preset,
            "message": self.case.prompt,
            "run_id": run_id,
            "profile_id": self.case.profile_id,
            "actor_tokens": {"tokens": tokens, "engine_bearer": self.engine_bearer},
            "metadata": meta,
        }
        if feature is not None:
            body["feature_tag"] = feature
        resp = await hc.post(f"{self.gateway_url}/v1/runs", json=body, timeout=60.0)
        assert resp.status_code == expect, (
            f"run-start expected {expect}, got {resp.status_code}: {resp.text}"
        )
        return resp

    async def _run_status(self, hc: httpx.AsyncClient) -> dict:
        """Poll the run record under the shared bounded transient-retry policy.

        A single dropped connection or read timeout on the gateway during a
        long-lived poll loop is transient (observed live: a healthy run killed
        at 118s by one ``RemoteProtocolError`` + ``ReadTimeout``); the same
        policy the engine client uses absorbs it, while a 4xx still surfaces
        immediately as a real routing/identity error.
        """

        async def attempt() -> dict:
            resp = await hc.get(
                f"{self.gateway_url}/v1/runs/{self.run_id}", timeout=30.0
            )
            resp.raise_for_status()
            return resp.json()

        return await _retry_transient(
            attempt,
            name=f"gateway status poll {self.run_id!r}",
            is_transient=_gateway_is_transient,
        )

    async def _assert_not_terminal(self, hc: httpx.AsyncClient) -> None:
        status = await self._run_status(hc)
        phase = status.get("semantic_phase")
        if phase and (not self.phases_seen or self.phases_seen[-1] != phase):
            self.phases_seen.append(phase)
        if status.get("status") in {"failed", "cancelled"}:
            raise AssertionError(f"run terminal failure: {json.dumps(status)[:800]}")

    # ------------------------------------------------------------------
    # Operation mode (the AUTO lane device)
    # ------------------------------------------------------------------

    async def _set_mode(
        self, ec: AuthoringClient, mode: str, *, setter_token: str
    ) -> int:
        """Set the worktree operation mode; return its requeued_approvals count.

        The scope is backend-derived. A downgrade (e.g. autonomous -> manual)
        re-queues NOT-YET-APPLYING system approvals for human review; an
        already-applied changeset is past that seam and is never disturbed
        (engine `modes.rs` `requeue_system_approvals` gates on Approved heads).
        """
        result = await ec.post_command(
            "/v1/mode",
            "set_operation_mode",
            {"mode": mode},
            idempotency_key=self._idk(f"mode-{mode}"),
            actor_token=setter_token,
        )
        if isinstance(result, Denial):
            raise AssertionError(
                f"set mode {mode} denied ({result.denial_kind}): {result.reason}"
            )
        assert result.data.get("status") in {"recorded", "replayed"}, (
            f"unexpected mode-set status: {result.data}"
        )
        assert result.data.get("mode") == mode, f"mode not applied: {result.data}"
        self._current_mode = mode
        requeued = result.data.get("requeued_approvals")
        return requeued if isinstance(requeued, int) else 0

    async def _ensure_mode(
        self, ec: AuthoringClient, mode: str, *, setter_token: str
    ) -> int | None:
        """Set the mode if it differs; return its requeued_approvals, else None."""
        if self._current_mode != mode:
            return await self._set_mode(ec, mode, setter_token=setter_token)
        return None

    @staticmethod
    def _mode_for(policy: str) -> str:
        return _MODE_AUTONOMOUS if policy == POLICY_AUTO else _MODE_MANUAL

    # ------------------------------------------------------------------
    # Gate discovery
    # ------------------------------------------------------------------

    async def _find_queue_item(
        self, ec: AuthoringClient, handled: set[str]
    ) -> dict | None:
        """A needs-review queue item for this run whose proposal is unhandled."""
        resp = await ec.get("/v1/review-queue", with_actor=False)
        for item in _items(resp.data):
            changeset = _dig(item, "changeset_id") or ""
            proposal = _dig(item, "proposal_id")
            if self.run_id in changeset and proposal and proposal not in handled:
                return item
        return None

    async def _find_policy_marker(
        self, ec: AuthoringClient, handled: set[str]
    ) -> dict | None:
        """An applied-under-policy (system-auto-approved) marker for this run."""
        resp = await ec.get("/v1/proposals", with_actor=False)
        data = resp.data if isinstance(resp.data, dict) else {}
        lane = data.get("applied_under_policy")
        for item in _items(lane):
            changeset = _dig(item, "changeset_id") or ""
            if self.run_id in changeset and changeset not in handled:
                return item
        return None

    async def _marker_applied(self, ec: AuthoringClient, changeset_id: str) -> bool:
        """True if *changeset_id* still holds an applied system-policy marker."""
        resp = await ec.get("/v1/proposals", with_actor=False)
        data = resp.data if isinstance(resp.data, dict) else {}
        for item in _items(data.get("applied_under_policy")):
            if (_dig(item, "changeset_id") or "") != changeset_id:
                continue
            proposal = item.get("proposal")
            return isinstance(proposal, dict) and proposal.get("status") == "applied"
        return False

    # ------------------------------------------------------------------
    # Verdict choreography
    # ------------------------------------------------------------------

    async def _decide(
        self,
        ec: AuthoringClient,
        item: dict,
        *,
        decision: str,
        reviewer_token: str,
        gate: str,
    ) -> None:
        """POST one review decision (approve / edit) over the engine surface."""
        proposal_id = _dig(item, "proposal_id")
        approval_id = _dig(item, "approval_id")
        reviewed_revision = _dig(item, "reviewed_proposal_revision")
        assert proposal_id and approval_id and reviewed_revision, (
            f"review item missing decision ids: {json.dumps(item)[:600]}"
        )
        result = await ec.post_command(
            f"/v1/reviews/{approval_id}/decisions",
            _DECISION_COMMAND[decision],
            {
                "proposal_id": proposal_id,
                "approval_id": approval_id,
                "decision": decision,
                "reviewed_revision": reviewed_revision,
                "comment": f"{gate} gate {decision} (acceptance harness)",
            },
            idempotency_key=self._idk(f"decide-{gate}-{decision}"),
            actor_token=reviewer_token,
        )
        if isinstance(result, Denial):
            raise AssertionError(
                f"{gate} {decision} denied ({result.denial_kind}): {result.reason}"
            )
        assert result.data.get("status") in {"decided", "replayed"}, (
            f"{gate} {decision} unexpected status: {result.data}"
        )

    async def _assert_reviewed_revision_fence(
        self, ec: AuthoringClient, item: dict, *, reviewer_token: str, gate: str
    ) -> None:
        """A decision attesting a STALE reviewed_revision must be a typed 409.

        The reviewed_revision is the edge contract's revision fence: the reviewer
        attests the exact revision the approval was opened against, and the engine
        raises `authoring_stale_review` (HTTP 409, `handlers2.rs:543`) on any
        mismatch rather than silently deciding a superseded revision. Probe it with
        a grammar-valid but wrong token; the real decision below uses the true one.
        The queued approval is untouched (the fence fires before any decision).
        """
        proposal_id = _dig(item, "proposal_id")
        approval_id = _dig(item, "approval_id")
        assert proposal_id and approval_id
        with pytest.raises(AuthoringTransportError) as excinfo:
            await ec.post_command(
                f"/v1/reviews/{approval_id}/decisions",
                _DECISION_COMMAND[_DECISION_APPROVE],
                {
                    "proposal_id": proposal_id,
                    "approval_id": approval_id,
                    "decision": _DECISION_APPROVE,
                    "reviewed_revision": "blob:pw7stalefence0000",
                    "comment": f"{gate} stale-revision fence probe (harness)",
                },
                idempotency_key=self._idk(f"fence-{gate}"),
                actor_token=reviewer_token,
            )
        assert excinfo.value.status_code == 409, (
            f"{gate} stale reviewed_revision was not a 409: {excinfo.value.status_code}"
        )
        assert excinfo.value.error_kind == "authoring_stale_review", (
            f"{gate} stale fence wrong error_kind: {excinfo.value.error_kind}"
        )

    async def _apply(
        self, ec: AuthoringClient, item: dict, *, reviewer_token: str, gate: str
    ) -> Materialization:
        """Apply an approved changeset and return its materialization receipt."""
        changeset_id = _dig(item, "changeset_id")
        approval_id = _dig(item, "approval_id")
        assert changeset_id and approval_id
        result = await ec.post_command(
            "/v1/apply-requests",
            "request_apply",
            {"changeset_id": changeset_id, "approval_id": approval_id},
            idempotency_key=self._idk(f"apply-{gate}"),
            actor_token=reviewer_token,
        )
        if isinstance(result, Denial):
            raise AssertionError(
                f"{gate} apply denied ({result.denial_kind}): {result.reason}"
            )
        assert result.data.get("status") in {"recorded", "replayed"}, (
            f"{gate} apply unexpected status: {result.data}"
        )
        assert result.data.get("child_outcome") == "applied", (
            f"{gate} apply did not materialize: {result.data}"
        )
        child = ((result.data.get("receipt") or {}).get("child")) or {}
        return Materialization(
            gate=gate,
            source="human",
            changeset_id=changeset_id,
            document_path=child.get("document_path"),
            result_stem=child.get("result_stem"),
        )

    async def _drive_human_gate(
        self,
        ec: AuthoringClient,
        hc: httpx.AsyncClient,
        *,
        gate: str,
        reviewer_token: str,
        handled: set[str],
        poll_seconds: float,
        deadline: float,
    ) -> None:
        """Reject-with-notes -> revision -> approve -> apply for one human gate."""
        # 1. Park at the gate.
        first = await self._await(
            lambda: self._find_queue_item(ec, handled),
            hc,
            deadline,
            poll_seconds,
            what=f"{gate} gate to park for human review",
        )
        rejected_proposal = _dig(first, "proposal_id")
        assert rejected_proposal
        # 2. The revision fence: a stale reviewed_revision is a typed 409, never a
        # silently-decided superseded revision (edge contract).
        await self._assert_reviewed_revision_fence(
            ec, first, reviewer_token=reviewer_token, gate=gate
        )
        # 3. Reject with notes (request-changes): back to the writer, approval staled.
        await self._decide(
            ec, first, decision=_DECISION_EDIT, reviewer_token=reviewer_token, gate=gate
        )
        handled.add(rejected_proposal)
        # 4. The run must re-author and re-submit - the revision loop, not a dead end.
        revised = await self._await(
            lambda: self._find_queue_item(ec, handled),
            hc,
            deadline,
            poll_seconds,
            what=f"{gate} gate to re-submit after request-changes (revision routing)",
        )
        revised_proposal = _dig(revised, "proposal_id")
        assert revised_proposal and revised_proposal != rejected_proposal, (
            "request-changes did not route back to a fresh proposal"
        )
        # 5. Approve unparks the run; 6. apply materializes.
        await self._decide(
            ec,
            revised,
            decision=_DECISION_APPROVE,
            reviewer_token=reviewer_token,
            gate=gate,
        )
        materialization = await self._apply(
            ec, revised, reviewer_token=reviewer_token, gate=gate
        )
        handled.add(revised_proposal)
        self.materializations.append(materialization)

    async def _drive_auto_gate(
        self,
        ec: AuthoringClient,
        hc: httpx.AsyncClient,
        *,
        gate: str,
        handled_changesets: set[str],
        poll_seconds: float,
        deadline: float,
    ) -> None:
        """Assert the system operation-modes auto-approval + materialization."""
        marker = await self._await(
            lambda: self._find_policy_marker(ec, handled_changesets),
            hc,
            deadline,
            poll_seconds,
            what=f"{gate} gate to system-auto-approve under operation modes",
        )
        # The anti-bypass invariant: a SystemPolicyApprovalRecord under the
        # system:operation-modes actor, DISTINCT from any human decision record -
        # never merely "the run finished".
        system_actor = marker.get("system_actor")
        assert isinstance(system_actor, dict), f"marker has no system_actor: {marker}"
        assert system_actor.get("id") == _SYSTEM_AUTO_APPROVER_ID, (
            f"{gate} auto-approval was not the operation-modes actor: {system_actor}"
        )
        assert system_actor.get("kind") == "system", (
            f"{gate} auto-approver is not system-kind: {system_actor}"
        )
        assert marker.get("mode") == _MODE_AUTONOMOUS, (
            f"{gate} marker mode is not autonomous: {marker.get('mode')}"
        )
        assert marker.get("policy_id") == _MODE_POLICY_ID, (
            f"{gate} marker policy id mismatch: {marker.get('policy_id')}"
        )
        proposal = marker.get("proposal")
        assert isinstance(proposal, dict) and proposal.get("status") == "applied", (
            f"{gate} system-approved proposal did not apply: {proposal}"
        )
        changeset_id = _dig(marker, "changeset_id") or ""
        handled_changesets.add(changeset_id)
        self.materializations.append(
            Materialization(gate=gate, source="auto", changeset_id=changeset_id)
        )

    async def _await(
        self,
        find,
        hc: httpx.AsyncClient,
        deadline: float,
        poll_seconds: float,
        *,
        what: str,
    ) -> dict:
        """Poll *find* until it yields an item, watching for a terminal run."""
        while time.monotonic() < deadline:
            await self._assert_not_terminal(hc)
            found = await find()
            if found is not None:
                return found
            await asyncio.sleep(poll_seconds)
        raise AssertionError(f"timed out waiting for {what}; phases={self.phases_seen}")

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def _runtime_budget(self) -> float:
        """This lane's deadline - the shared budget also armed as the timeout marker.

        Delegates to the module-level :func:`_runtime_budget_for` so the harness's
        own deadline and the per-case ``pytest-timeout`` marker are one formula and
        can never drift.
        """
        return _runtime_budget_for(self.case)

    async def run(
        self, *, timeout_seconds: float | None = None, poll_seconds: float = 5.0
    ) -> list[str]:
        """Drive the full loop; return the ordered list of gates driven."""
        gate_names = list(self.case.gate_policy) or ["gate"]
        if timeout_seconds is None:
            timeout_seconds = self._runtime_budget()
        deadline = time.monotonic() + timeout_seconds
        async with _ResilientAuthoringClient(
            self.engine_base_url, self.engine_bearer
        ) as ec:
            tokens = {
                role: await self._mint(ec, f"agent:{self.run_id}:{role}", "agent")
                for role in self.case.roles
            }
            # One human principal is both the reviewer AND the operation-mode
            # policy setter (mode-set requires a human/system actor; a human
            # reviewer distinct from the agent author clears the self-approval ban).
            reviewer_human = await self._mint(ec, f"rev-human:{self.run_id}", "human")

            async with httpx.AsyncClient() as hc:
                # Hardened run-start refusals (pure eligibility, no submit).
                await self._run_start(
                    hc,
                    run_id=f"{self.run_id}-no-feature",
                    tokens=tokens,
                    feature=None,
                    expect=422,
                )
                partial = {k: v for k, v in tokens.items() if k != self.case.roles[-1]}
                await self._run_start(
                    hc,
                    run_id=f"{self.run_id}-missing-role",
                    tokens=partial,
                    feature=self.feature,
                    expect=422,
                )

                # The first gate's mode must be live BEFORE the run submits it.
                await self._ensure_mode(
                    ec,
                    self._mode_for(self.case.gate_policy[gate_names[0]]),
                    setter_token=reviewer_human,
                )
                await self._run_start(
                    hc,
                    run_id=self.run_id,
                    tokens=tokens,
                    feature=self.feature,
                    expect=201,
                )

                handled_proposals: set[str] = set()
                handled_changesets: set[str] = set()
                gates_done: list[str] = []
                for index, gate in enumerate(gate_names):
                    policy = self.case.gate_policy[gate]
                    if policy == POLICY_AUTO:
                        await self._drive_auto_gate(
                            ec,
                            hc,
                            gate=gate,
                            handled_changesets=handled_changesets,
                            poll_seconds=poll_seconds,
                            deadline=deadline,
                        )
                    else:
                        await self._drive_human_gate(
                            ec,
                            hc,
                            gate=gate,
                            reviewer_token=reviewer_human,
                            handled=handled_proposals,
                            poll_seconds=poll_seconds,
                            deadline=deadline,
                        )
                    gates_done.append(gate)
                    # Switch the mode for the NEXT gate before the run submits it.
                    # The AUTO marker is written synchronously at submit time, so this
                    # switch lands before the resumed run authors the next document.
                    if index + 1 < len(gate_names):
                        next_policy = self.case.gate_policy[gate_names[index + 1]]
                        next_mode = self._mode_for(next_policy)
                        requeued = await self._ensure_mode(
                            ec, next_mode, setter_token=reviewer_human
                        )
                        # MIXED per-gate seam (rider): an AUTO->HUMAN downgrade must
                        # NOT disturb the AUTO gate's ALREADY-APPLIED document - it is
                        # past the requeue seam, so the downgrade requeues nothing and
                        # its applied-under-policy marker stays applied.
                        if (
                            policy == POLICY_AUTO
                            and next_mode == _MODE_MANUAL
                            and requeued is not None
                        ):
                            assert requeued == 0, (
                                f"downgrade after applied AUTO gate {gate!r} requeued "
                                f"{requeued} approvals; the applied doc was disturbed"
                            )
                            applied_changeset = self.materializations[-1].changeset_id
                            assert await self._marker_applied(ec, applied_changeset), (
                                f"AUTO gate {gate!r} marker no longer applied after "
                                f"the mode downgrade: {applied_changeset}"
                            )
                return gates_done

    def materialized(self) -> dict[str, list[Path]]:
        """Return the materialized markdown documents per expected doc kind.

        Filtered to this run's feature so a leftover document from another run is
        never counted as this run's materialization.
        """
        out: dict[str, list[Path]] = {}
        for kind in self.case.expected_doc_kinds:
            directory = self.vault_root / kind
            files = (
                sorted(directory.glob(f"*{self.feature}*.md"))
                if directory.is_dir()
                else []
            )
            out[kind] = files
        return out


def _reachable_stack() -> tuple[str, str, Path] | None:
    """Resolve (engine_base_url, engine_bearer, vault_root) or None if unreachable."""
    endpoint = resolve_engine()
    if endpoint is None:
        return None
    try:
        health = httpx.get(f"{_GATEWAY_URL}/api/health", timeout=3.0)
    except httpx.HTTPError:
        return None
    if health.status_code != 200:
        return None
    service_json = os.environ.get("VAULTSPEC_ENGINE_SERVICE_JSON")
    if not service_json:
        return None
    vault_root = Path(service_json).parents[2]  # <ws>/.vault
    return endpoint.base_url, endpoint.bearer_token, vault_root


@pytest.mark.service
@pytest.mark.asyncio
@pytest.mark.parametrize("case", [_case_param(c) for c in _ALL_CASES])
async def test_pw7_research_adr_materializes_two_documents(
    case: AcceptanceCase,
) -> None:
    """The research_adr loop materializes exactly the expected document set.

    Drives the standing acceptance case end to end and asserts a research and
    an ADR document materialize under the engine workspace ``.vault/`` - the
    document-materialization contract for ``research_adr`` (N = 2) - across the
    three verdict lanes (HUMAN reject-with-notes -> revision -> approve; AUTO
    operation-modes system approval; MIXED per-gate). Verdicts are driven
    programmatically over the engine surface.
    """
    missing = [name for name in case.required_env if not os.environ.get(name)]
    if missing:
        pytest.skip(
            f"{case.label} lane is credential-gated: missing {', '.join(missing)} "
            "in the environment. This is a truthful skip, not a masked failure - "
            "set the credential to run the lane against its real provider."
        )
    stack = _reachable_stack()
    if stack is None:
        pytest.skip(
            "no reachable loopback stack; boot a workspace-local `vaultspec serve "
            "--no-seat` engine plus the a2a gateway/worker with "
            "VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true (runbook), then "
            "set VAULTSPEC_ENGINE_SERVICE_JSON and select -m service"
        )
    engine_base_url, engine_bearer, vault_root = stack
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
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
