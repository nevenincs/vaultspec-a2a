"""Headless acceptance harness for the document-authoring loop, and its toolkit.

The STANDING acceptance driver for the research-to-ADR phase machine, built as a
reusable, parameterized harness rather than a one-off so the successor document
workloads (curation, plan-authoring) reuse it. Given a case it drives one run end
to end against the live loopback stack and reports which documents materialized
under ``.vault/``.

The loop :class:`AcceptanceHarness` drives, all live and mock-free:

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
    The harness asserts that system marker, never a human decision - the
    operation-modes anti-bypass invariant, not merely "the run completed fast";
* a case may give each gate a different policy, sequenced by a timed mode
  transition, which is what proves the policy is per gate rather than per run.

Orthogonal to the verdict lane is the PROVIDER axis: a case names the provider it
certifies and :func:`resolve_selection` turns the operator's served-catalog
declaration into the run-start ``selection`` and per-role ``overrides``, skipping
rather than certifying a provider the case makes no claim about.

Gate detection keys on the ENGINE surface (a queued proposal / an applied-under-
policy marker scoped to this run's changeset id ``cs:<run_id>:<phase>-r<cycle>``),
not the a2a semantic phase, so it is robust to the reconciler masking the semantic
phase after a subscriber resume.

Wire shapes are grounded in the engine Rust source (read-only), not prose:
``ReviewDecisionRequest`` (``decision`` enum ``approve|reject|edit|respond``,
load-bearing ``reviewed_revision``), ``ApplyRequest`` (``changeset_id`` +
``approval_id``), ``SetOperationModeRequest`` (``mode`` enum
``manual|assisted|autonomous``, human/system actor only), the apply receipt's
``child.{document_path,result_stem,outcome}``, and the ``applied_under_policy``
projection lane carrying ``system_actor`` / ``mode`` / ``policy_id``.

The live proofs that observe a run rather than drive its gates share the rest of
this module: :func:`reachable_stack` for the infrastructure gate, a document-tree
snapshot that proves a run wrote nothing to ``.vault``, the narration a message
frame carries, and the engine-side changeset reader the bridged-authoring proofs
key on. :func:`reachable_stack` returns ``None`` rather than raising when no
loopback engine or gateway is reachable, so a caller reports the absent stack as a
prerequisite instead of a failure.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import httpx
import pytest

from ..authoring import (
    AuthoringClient,
    AuthoringResponse,
    AuthoringTransportError,
    Denial,
    mint_actor_token,
    resolve_engine,
)
from ..graph.enums import PermissionOptionKind, ServerEventType, ToolKind
from ..streaming.sse_frames import iter_sse_events
from .catalog import (
    NoSelectableLaneError,
    async_fetch_provider_catalog,
    in_process_selection,
    override_selection_from_served_catalog,
    selection_from_served_catalog,
)
from .endpoints import resolve_gateway_url
from .payloads import json_object, json_object_list
from .sse import SseFrame

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ..conftest import ExternalPrerequisiteRule
    from ..providers._json_contract import JsonObject

__all__ = [
    "CODER_ROLE",
    "GATEWAY_AUTH_HEADERS",
    "MODE_AUTONOMOUS",
    "MODE_MANUAL",
    "OBSERVE_DEADLINE_SECONDS",
    "POLICY_AUTO",
    "POLICY_HUMAN",
    "PRESET_DETERMINISTIC",
    "PRESET_LIVE",
    "SOLO_CODER_PRESET",
    "AcceptanceCase",
    "AcceptanceHarness",
    "Materialization",
    "ResilientAuthoringClient",
    "is_live_lane",
    "message_content",
    "observe_bridged_authoring_run",
    "reachable_stack",
    "resolve_selection",
    "runtime_budget_for",
    "snapshot_vault",
    "vault_write_delta",
]

# A doc-authoring role may only ever need read-only research tools; any other
# tool-permission request (a write/execute/unclassified kind) is a real acceptance
# failure, never allow_alwayed. Keyed on the ACP ToolKind the engine tags each
# permission with.
_READ_ONLY_TOOL_KINDS = frozenset(
    {ToolKind.READ, ToolKind.SEARCH, ToolKind.FETCH, ToolKind.THINK}
)


def _option_id_for(options: Sequence[Mapping[str, object]], kind: str) -> str | None:
    """Return the option_id of the first permission option of *kind*, or None."""
    for option in options:
        if option.get("kind") == kind:
            option_id = option.get("option_id")
            if isinstance(option_id, str):
                return option_id
    return None


logger = logging.getLogger(__name__)


# The gateway fails closed on every /v1/ route (`api/auth.py`'s
# `authenticate_request`), so the caller must present the gateway's own
# service-discovery bearer - the same VAULTSPEC_A2A_GATEWAY_TOKEN the booting
# shell configured the gateway process with. Absent, requests degrade
# to unauthenticated and the gateway answers a truthful 401/503; that is a loud
# failure rather than a silently skipped assertion, which is the point.
_GATEWAY_SERVICE_TOKEN = os.environ.get("VAULTSPEC_A2A_GATEWAY_TOKEN", "")
GATEWAY_AUTH_HEADERS = (
    {"Authorization": f"Bearer {_GATEWAY_SERVICE_TOKEN}"}
    if _GATEWAY_SERVICE_TOKEN
    else {}
)

# Per-gate verdict policies (the lane axis).
POLICY_AUTO = "AUTO"
POLICY_HUMAN = "HUMAN"

# Operation-mode wire values (engine `OperationMode`, snake_case).
MODE_MANUAL = "manual"
MODE_AUTONOMOUS = "autonomous"

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
# Provider.DETERMINISTIC device: the fast, provider-agnostic lane run on every
# dispatch. LIVE is the real-Claude preset: the real-provider proof, run once the
# deterministic lanes are green; select it with `-k live`.
PRESET_DETERMINISTIC = "vaultspec-adr-research-deterministic"
PRESET_LIVE = "vaultspec-adr-research"


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
    lane_provider:     The provider this lane certifies, or ``None`` for a lane
                       that is provider-agnostic (the deterministic in-process
                       cases, which take whatever selectable lane the gateway
                       serves). When set, the operator's configured live
                       selection MUST name this provider or the case skips - a
                       lane that quietly certified whichever provider happened to
                       be configured would be reporting someone else's result.
    requires_live_selection:
                       The lane must run on the operator-configured REAL
                       provider lane, even when it claims no specific
                       provider. Without this a provider-agnostic case would
                       accept whatever the gateway serves - including an
                       in-process lane - and a "real-provider" proof would
                       quietly stop being one.
    override_roles:    Roles routed to the SECOND declared lane, making the run
                       genuinely mixed-provider. Non-empty requires the override
                       selector to be configured; absent it the case skips rather
                       than degrading to a single-lane run under a mixed label.
    required_prerequisites:
                       External prerequisite ids that MUST be present for the lane
                       to run (a credential-gated lane). An absent one is reported
                       through the repository's prerequisite rule, never a faked
                       pass.
    autonomous:        Dispatch the run with ``autonomous=True``, the headless
                       target mode: the worker skips permission-callback wiring
                       entirely (``worker.py`` autonomy branch), so a live model's
                       read-only tool use (web search) proceeds without parking
                       the run on a permission interrupt nothing answers.
    """

    label: str
    preset: str
    feature: str
    prompt: str
    roles: tuple[str, ...]
    expected_doc_kinds: tuple[str, ...]
    gate_policy: dict[str, str] = field(default_factory=dict)
    lane_provider: str | None = None
    requires_live_selection: bool = False
    override_roles: tuple[str, ...] = ()
    required_prerequisites: tuple[str, ...] = ()
    autonomous: bool = False


@dataclass(frozen=True, slots=True)
class _HumanGateContext:
    """Runtime values shared by one human gate's polling and decisions."""

    gate: str
    reviewer_token: str
    handled: set[str]
    poll_seconds: float
    deadline: float


@dataclass(frozen=True, slots=True)
class _AutoGateContext:
    """Runtime values shared by one automatic gate's polling and receipt."""

    gate: str
    handled_changesets: set[str]
    poll_seconds: float
    deadline: float


def is_live_lane(case: AcceptanceCase) -> bool:
    """Whether a lane authors with a real provider (the LIVE preset), not the instant
    deterministic one - the single source for every live/deterministic branch."""
    return case.preset == PRESET_LIVE


def _poll_seconds_for(case: AcceptanceCase) -> float:
    """Status-poll cadence per lane: a real-provider lane authors in minutes/turn so
    a slow 5s poll is fine; a deterministic lane resolves each transition in well
    under a second, so a 1s poll reclaims the ~4s/transition of pure wait a 5s
    cadence adds without any coverage loss."""
    return 5.0 if is_live_lane(case) else 1.0


def runtime_budget_for(case: AcceptanceCase) -> float:
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
    return budget * (4.0 if is_live_lane(case) else 1.0)


async def _served_catalog(gateway_url: str, workspace_root: str) -> JsonObject:
    """Read the catalog this workspace is actually served, cold-build budget included.

    A first read on a gateway probes every registered lane over real subprocesses
    and network calls, so this carries its own generous timeout rather than the
    status-poll one.
    """
    async with httpx.AsyncClient(
        base_url=gateway_url, headers=GATEWAY_AUTH_HEADERS
    ) as hc:
        payload = await async_fetch_provider_catalog(hc, workspace_root)
    return json_object(payload, at="gateway provider-catalog response")


def _deterministic_selection(
    catalog: JsonObject, external_prerequisite: ExternalPrerequisiteRule
) -> JsonObject:
    """Select an in-process lane for a case that makes no provider claim.

    The deterministic lanes assert on the document loop and its gates, not on
    which provider produced the text, so any in-process lane satisfies them.
    "Any SELECTABLE lane" is a different and much wider thing: on a host holding
    a live provider session that resolves to a real metered lane, which would
    have this suite billing a provider for a case whose whole point is that no
    provider claim is being made. The mechanism cannot return one.
    """
    try:
        return in_process_selection(catalog)
    except NoSelectableLaneError as exc:
        external_prerequisite.absent(
            "in-process-lanes",
            f"a deterministic case cannot present a valid selection: {exc}. "
            "Cases that DO make a provider claim declare their lane explicitly "
            "instead",
        )


async def resolve_selection(
    case: AcceptanceCase,
    gateway_url: str,
    workspace_root: str,
    external_prerequisite: ExternalPrerequisiteRule,
) -> tuple[JsonObject, dict[str, JsonObject]]:
    """Resolve the run-start selection (and any per-role overrides) for *case*.

    This is where the retired provider-axis PROFILES now live. A profile used to
    name lanes inside the preset; the same routing is expressed here as the
    whole-team ``selection`` plus per-role ``overrides``, with the opaque
    identifiers supplied by the operator instead of authored in the repository.

    Every way this cannot honestly run is reported naming what is missing, never a
    quiet substitution: certifying a provider the case does not claim, or running
    a "mixed" lane on one provider, would both report a result nobody asked for.
    """
    catalog = await _served_catalog(gateway_url, workspace_root)

    if case.lane_provider is None and not case.requires_live_selection:
        return _deterministic_selection(catalog, external_prerequisite), {}

    claim = (
        f"certifies the {case.lane_provider!r} provider"
        if case.lane_provider is not None
        else "runs on a real provider"
    )
    external_prerequisite(
        "provider-catalog-live-selection",
        f"the {case.label} lane {claim}, which needs an explicit served selection",
    )
    selection = selection_from_served_catalog(catalog)
    if case.lane_provider is not None and (selection.provider_id != case.lane_provider):
        pytest.skip(
            f"the {case.label} lane certifies {case.lane_provider!r}, but the "
            f"configured live selection names {selection.provider_id!r}. Skipped "
            "rather than run, because a pass here would be recorded against a "
            "provider this lane makes no claim about."
        )

    if not case.override_roles:
        return selection.model_dump(mode="json"), {}

    external_prerequisite(
        "provider-catalog-override-selection",
        f"the {case.label} lane is MIXED-provider - it routes "
        f"{', '.join(case.override_roles)} to a second lane - so it needs a second "
        "explicit selection, and is never degraded to a single-lane run, which "
        "would keep the MIXED label on a run proving nothing mixed",
    )
    override = override_selection_from_served_catalog(catalog)
    if override.provider_id == selection.provider_id:
        pytest.skip(
            f"the {case.label} lane needs two DIFFERENT providers, but both the "
            f"primary and override selections name {override.provider_id!r}. That "
            "run would be single-provider wearing a mixed label."
        )
    override_body = override.model_dump(mode="json")
    return selection.model_dump(mode="json"), {
        role: dict(override_body) for role in case.override_roles
    }


def _object_list_or_empty(value: object, *, at: str) -> list[JsonObject]:
    """Read an optional object list: absent is empty, present must be objects."""
    return [] if value is None else json_object_list(value, at=at)


def _dig(item: JsonObject, field_name: str) -> str | None:
    """Return the first string value for *field_name* nested anywhere in *item*.

    *item* is already a validated JSON object, so every nested object is one too
    and an ``isinstance`` check is all that separates it from a scalar or list.
    """
    value = item.get(field_name)
    if isinstance(value, str):
        return value
    for nested in item.values():
        if not isinstance(nested, dict):
            continue
        found = _dig(nested, field_name)
        if found:
            return found
    return None


def _items(data: object, *, at: str) -> list[JsonObject]:
    """Read the optional ``items`` list from one service response object."""
    return _object_list_or_empty(
        json_object(data, at=at).get("items"), at=f"{at}.items"
    )


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


async def _retry_transient[T](
    op: Callable[[], Awaitable[T]],
    *,
    name: str,
    is_transient: Callable[[BaseException], bool],
    before_retry: Callable[[BaseException], Awaitable[bool]] | None = None,
) -> T:
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


class ResilientAuthoringClient(AuthoringClient):
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

    async def _call_resilient[T](
        self, op: Callable[[], Awaitable[T]], *, operation: str
    ) -> T:
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
            op,
            name=f"engine call {operation!r}",
            is_transient=is_transient,
            before_retry=before_retry,
        )

    @override
    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        with_actor: bool = False,
        actor_token: str | None = None,
    ) -> AuthoringResponse:
        return await self._call_resilient(
            lambda: AuthoringClient.get(
                self,
                path,
                params=params,
                with_actor=with_actor,
                actor_token=actor_token,
            ),
            operation="get",
        )

    @override
    async def post_command(
        self,
        path: str,
        command: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        actor_token: str | None = None,
    ) -> AuthoringResponse | Denial:
        return await self._call_resilient(
            lambda: AuthoringClient.post_command(
                self,
                path,
                command,
                payload,
                idempotency_key=idempotency_key,
                actor_token=actor_token,
            ),
            operation="post_command",
        )

    @override
    async def post_bare(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        with_actor: bool = False,
        actor_token: str | None = None,
    ) -> AuthoringResponse | Denial:
        return await self._call_resilient(
            lambda: AuthoringClient.post_bare(
                self,
                path,
                payload,
                with_actor=with_actor,
                actor_token=actor_token,
            ),
            operation="post_bare",
        )


@dataclass(slots=True)
class AcceptanceHarness:
    """Drives one acceptance case against the live loopback stack."""

    case: AcceptanceCase
    engine_base_url: str
    engine_bearer: str
    vault_root: Path
    gateway_url: str
    # The resolved run-start selection and per-role overrides. Injected by the
    # test rather than resolved here so every "cannot honestly run" path is a
    # pytest.skip at collection-adjacent scope, not an exception mid-run.
    selection: JsonObject = field(default_factory=dict)
    overrides: dict[str, JsonObject] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: f"pw7-{int(time.time())}")
    phases_seen: list[str] = field(default_factory=list)
    materializations: list[Materialization] = field(default_factory=list)
    feature: str = ""
    _idk_counter: itertools.count[int] = field(default_factory=itertools.count)
    _current_mode: str | None = None
    _answered_permissions: set[str] = field(default_factory=set)
    _permission_violations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Run-start refuses a body with no selection, and would do so as an opaque
        # 422 deep inside a booted stack. A harness built without one is a wiring
        # mistake in the caller, so it is named here instead - at construction,
        # before any token is minted or any provider is spawned.
        assert self.selection, (
            "AcceptanceHarness was built with no run-start selection; resolve one "
            "with resolve_selection(case, gateway_url, workspace_root, "
            "external_prerequisite) and pass it in. Run-start has no implicit "
            "provider default to fall back on."
        )
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

    async def mint(self, ec: AuthoringClient, actor_id: str, kind: str) -> str:
        """Mint one actor token of *kind* for *actor_id*; a denial fails the case."""
        minted = await mint_actor_token(ec, actor_id=actor_id, kind=kind)
        assert isinstance(minted, AuthoringResponse), f"mint denied: {minted}"
        token = json_object(minted.data, at="actor-token response").get("raw_token")
        assert isinstance(token, str) and token
        return token

    async def run_start(
        self,
        hc: httpx.AsyncClient,
        *,
        run_id: str,
        tokens: dict[str, str],
        feature: str | None,
        expect: int,
    ) -> httpx.Response:
        """POST run-start for this case and assert the status it answers."""
        meta: dict[str, object] = {
            "workspace_root": str(self.vault_root.parent),
            "nickname": run_id,
        }
        if feature is not None:
            meta["feature_tag"] = feature
        body: dict[str, object] = {
            "team_preset": self.case.preset,
            "message": self.case.prompt,
            "run_id": run_id,
            # Run-start requires this explicit selection and revalidates it
            # against the catalog served for this workspace.
            "selection": self.selection,
            "actor_tokens": {"tokens": tokens, "engine_bearer": self.engine_bearer},
            "metadata": meta,
        }
        if self.overrides:
            body["overrides"] = self.overrides
        if feature is not None:
            body["feature_tag"] = feature
        if self.case.autonomous:
            body["autonomous"] = True
        resp = await hc.post(f"{self.gateway_url}/v1/runs", json=body, timeout=60.0)
        assert resp.status_code == expect, (
            f"run-start expected {expect}, got {resp.status_code}: {resp.text}"
        )
        return resp

    async def run_status(self, hc: httpx.AsyncClient) -> JsonObject:
        """Poll the run record under the shared bounded transient-retry policy.

        A single dropped connection or read timeout on the gateway during a
        long-lived poll loop is transient (observed live: a healthy run killed
        at 118s by one ``RemoteProtocolError`` + ``ReadTimeout``); the same
        policy the engine client uses absorbs it, while a 4xx still surfaces
        immediately as a real routing/identity error.
        """

        async def attempt() -> JsonObject:
            resp = await hc.get(
                f"{self.gateway_url}/v1/runs/{self.run_id}", timeout=30.0
            )
            resp.raise_for_status()
            return json_object(resp.json(), at="gateway run-status response")

        return await _retry_transient(
            attempt,
            name=f"gateway status poll {self.run_id!r}",
            is_transient=_gateway_is_transient,
        )

    async def _assert_not_terminal(self, hc: httpx.AsyncClient) -> None:
        status = await self.run_status(hc)
        phase = status.get("semantic_phase")
        if isinstance(phase, str) and (
            not self.phases_seen or self.phases_seen[-1] != phase
        ):
            self.phases_seen.append(phase)
        if status.get("status") in {"failed", "cancelled"}:
            raise AssertionError(f"run terminal failure: {json.dumps(status)[:800]}")

    # ------------------------------------------------------------------
    # Operation mode (the AUTO lane device)
    # ------------------------------------------------------------------

    async def set_mode(
        self, ec: AuthoringClient, mode: str, *, setter_token: str
    ) -> int:
        """Set the worktree operation mode; return its requeued_approvals count.

        The scope is backend-derived. A downgrade (e.g. autonomous -> manual)
        re-queues NOT-YET-APPLYING system approvals for human review; an
        already-applied changeset is past that seam and is never disturbed
        (engine `modes.rs` `requeue_system_approvals` gates on Approved heads).

        Only the operator sets the engine's operation mode, and that is a
        preserved property rather than a gap: no ``api/``, ``control/``,
        ``graph/`` or ``providers/`` code calls the mode-setting endpoint, and
        this method is its one caller in the test tiers. A production call site
        would be a new decision, not a reuse of this one.
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
        data = json_object(result.data, at="mode-set response")
        assert data.get("status") in {"recorded", "replayed"}, (
            f"unexpected mode-set status: {data}"
        )
        assert data.get("mode") == mode, f"mode not applied: {data}"
        self._current_mode = mode
        requeued = data.get("requeued_approvals")
        return requeued if isinstance(requeued, int) else 0

    async def _ensure_mode(
        self, ec: AuthoringClient, mode: str, *, setter_token: str
    ) -> int | None:
        """Set the mode if it differs; return its requeued_approvals, else None."""
        if self._current_mode != mode:
            return await self.set_mode(ec, mode, setter_token=setter_token)
        return None

    @staticmethod
    def _mode_for(policy: str) -> str:
        return MODE_AUTONOMOUS if policy == POLICY_AUTO else MODE_MANUAL

    # ------------------------------------------------------------------
    # Gate discovery
    # ------------------------------------------------------------------

    async def _find_queue_item(
        self, ec: AuthoringClient, handled: set[str]
    ) -> JsonObject | None:
        """A needs-review queue item for this run whose proposal is unhandled."""
        resp = await ec.get("/v1/review-queue", with_actor=False)
        for item in _items(resp.data, at="review-queue response"):
            changeset = _dig(item, "changeset_id") or ""
            proposal = _dig(item, "proposal_id")
            if self.run_id in changeset and proposal and proposal not in handled:
                return item
        return None

    async def _find_policy_marker(
        self, ec: AuthoringClient, handled: set[str]
    ) -> JsonObject | None:
        """An applied-under-policy (system-auto-approved) marker for this run."""
        resp = await ec.get("/v1/proposals", with_actor=False)
        data = json_object(resp.data, at="proposals response")
        lane = data.get("applied_under_policy")
        for item in _items(lane, at="applied-under-policy lane"):
            changeset = _dig(item, "changeset_id") or ""
            if self.run_id in changeset and changeset not in handled:
                return item
        return None

    async def _marker_applied(self, ec: AuthoringClient, changeset_id: str) -> bool:
        """True if *changeset_id* still holds an applied system-policy marker."""
        resp = await ec.get("/v1/proposals", with_actor=False)
        data = json_object(resp.data, at="proposals response")
        for item in _items(
            data.get("applied_under_policy"), at="applied-under-policy lane"
        ):
            if (_dig(item, "changeset_id") or "") != changeset_id:
                continue
            proposal = item.get("proposal")
            if not isinstance(proposal, dict):
                return False
            return proposal.get("status") == "applied"
        return False

    # ------------------------------------------------------------------
    # Verdict choreography
    # ------------------------------------------------------------------

    async def _decide(
        self,
        ec: AuthoringClient,
        item: JsonObject,
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
        data = json_object(result.data, at=f"{gate} decision response")
        assert data.get("status") in {"decided", "replayed"}, (
            f"{gate} {decision} unexpected status: {data}"
        )

    async def _assert_reviewed_revision_fence(
        self, ec: AuthoringClient, item: JsonObject, *, reviewer_token: str, gate: str
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
        self, ec: AuthoringClient, item: JsonObject, *, reviewer_token: str, gate: str
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
        data = json_object(result.data, at=f"{gate} apply response")
        assert data.get("status") in {"recorded", "replayed"}, (
            f"{gate} apply unexpected status: {data}"
        )
        assert data.get("child_outcome") == "applied", (
            f"{gate} apply did not materialize: {data}"
        )
        receipt = json_object(data.get("receipt"), at=f"{gate} apply receipt")
        child = json_object(receipt.get("child"), at=f"{gate} apply receipt child")
        return Materialization(
            gate=gate,
            source="human",
            changeset_id=changeset_id,
            document_path=(
                document_path
                if isinstance(document_path := child.get("document_path"), str)
                else None
            ),
            result_stem=(
                result_stem
                if isinstance(result_stem := child.get("result_stem"), str)
                else None
            ),
        )

    async def _drive_human_gate(
        self,
        ec: AuthoringClient,
        hc: httpx.AsyncClient,
        context: _HumanGateContext,
    ) -> None:
        """Reject-with-notes -> revision -> approve -> apply for one human gate."""
        gate = context.gate
        reviewer_token = context.reviewer_token
        handled = context.handled
        poll_seconds = context.poll_seconds
        deadline = context.deadline
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
        context: _AutoGateContext,
    ) -> None:
        """Assert the system operation-modes auto-approval + materialization."""
        gate = context.gate
        handled_changesets = context.handled_changesets
        poll_seconds = context.poll_seconds
        deadline = context.deadline
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
        system_actor = json_object(
            marker.get("system_actor"), at=f"{gate} policy marker system actor"
        )
        assert system_actor.get("id") == _SYSTEM_AUTO_APPROVER_ID, (
            f"{gate} auto-approval was not the operation-modes actor: {system_actor}"
        )
        assert system_actor.get("kind") == "system", (
            f"{gate} auto-approver is not system-kind: {system_actor}"
        )
        assert marker.get("mode") == MODE_AUTONOMOUS, (
            f"{gate} marker mode is not autonomous: {marker.get('mode')}"
        )
        assert marker.get("policy_id") == _MODE_POLICY_ID, (
            f"{gate} marker policy id mismatch: {marker.get('policy_id')}"
        )
        proposal = json_object(
            marker.get("proposal"), at=f"{gate} policy marker proposal"
        )
        assert proposal.get("status") == "applied", (
            f"{gate} system-approved proposal did not apply: {proposal}"
        )
        changeset_id = _dig(marker, "changeset_id") or ""
        handled_changesets.add(changeset_id)
        self.materializations.append(
            Materialization(gate=gate, source="auto", changeset_id=changeset_id)
        )

    async def _respond_permission(
        self, hc: httpx.AsyncClient, request_id: str, option_id: str
    ) -> None:
        """POST a permission response (best-effort; retried on the next poll)."""
        with contextlib.suppress(httpx.HTTPError):
            await hc.post(
                f"{self.gateway_url}/v1/runs/{self.run_id}"
                f"/permissions/{request_id}/respond",
                json={"option_id": option_id},
                timeout=30.0,
            )

    async def _answer_pending_permissions(self, hc: httpx.AsyncClient) -> None:
        """Answer outstanding tool-permission interrupts for a non-autonomous live run.

        A live researcher's read-only tool request (WebSearch etc.) interrupts the run
        by design; without an answer it parks forever. Read-only research tools get
        ``allow_always`` so the run progresses; any other kind is denied AND recorded
        as a violation (a doc-authoring role must never need a write/execute tool),
        which fails the lane at the end. Best-effort per poll: a transient state-read
        error is retried on the next tick.
        """
        try:
            resp = await hc.get(
                f"{self.gateway_url}/v1/runs/{self.run_id}/history", timeout=10.0
            )
        except httpx.HTTPError:
            return
        if resp.status_code != 200:
            return
        # The history verb embeds the state snapshot rather than restating it.
        history = json_object(resp.json(), at="gateway history response")
        snapshot = json_object(history.get("state"), at="gateway history state")
        for perm in _object_list_or_empty(
            snapshot.get("pending_permissions"), at="gateway pending permissions"
        ):
            request_id = perm.get("request_id")
            if not isinstance(request_id, str):
                continue
            if request_id in self._answered_permissions:
                continue
            self._answered_permissions.add(request_id)
            options = _object_list_or_empty(
                perm.get("options"), at="permission options"
            )
            tool_kind = perm.get("tool_kind")
            if isinstance(tool_kind, str) and tool_kind in _READ_ONLY_TOOL_KINDS:
                option_id = _option_id_for(options, PermissionOptionKind.ALLOW_ALWAYS)
                if option_id is not None:
                    await self._respond_permission(hc, request_id, option_id)
            else:
                self._permission_violations.append(
                    f"{tool_kind!r}: {perm.get('description', '')}"
                )
                deny_id = _option_id_for(options, PermissionOptionKind.REJECT_ALWAYS)
                if deny_id is not None:
                    await self._respond_permission(hc, request_id, deny_id)

    async def _await(
        self,
        find: Callable[[], Awaitable[JsonObject | None]],
        hc: httpx.AsyncClient,
        deadline: float,
        poll_seconds: float,
        *,
        what: str,
    ) -> JsonObject:
        """Poll *find* until it yields an item, watching for a terminal run."""
        started = time.monotonic()
        # A non-autonomous live run can interrupt on a tool-permission request while
        # we wait for a gate; answer read-only ones inline so it progresses. Skipped
        # for deterministic/autonomous lanes (they never interrupt) to keep them fast.
        answer_permissions = is_live_lane(self.case) and not self.case.autonomous
        while time.monotonic() < deadline:
            await self._assert_not_terminal(hc)
            if answer_permissions:
                await self._answer_pending_permissions(hc)
            found = await find()
            if found is not None:
                # Per-transition wall time - the harness's own runtime profile.
                # A throwaway overlay of this line attributed the 300-900s lane
                # runtimes to since-fixed stalls (the healthy mixed lane runs in
                # ~8s); keeping it at debug makes the next regression visible
                # per-phase instead of as an opaque slow test.
                logger.debug(
                    "pw7 await %s: %.2fs (poll=%.1fs)",
                    what,
                    time.monotonic() - started,
                    poll_seconds,
                )
                return found
            await asyncio.sleep(poll_seconds)
        raise AssertionError(f"timed out waiting for {what}; phases={self.phases_seen}")

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def _runtime_budget(self) -> float:
        """This lane's deadline - the shared budget also armed as the timeout marker.

        Delegates to the module-level :func:`runtime_budget_for` so the harness's
        own deadline and the per-case ``pytest-timeout`` marker are one formula and
        can never drift.
        """
        return runtime_budget_for(self.case)

    async def run(
        self, *, timeout_seconds: float | None = None, poll_seconds: float | None = None
    ) -> list[str]:
        """Drive the full loop; return the ordered list of gates driven."""
        gate_names = list(self.case.gate_policy) or ["gate"]
        if timeout_seconds is None:
            timeout_seconds = self._runtime_budget()
        if poll_seconds is None:
            poll_seconds = _poll_seconds_for(self.case)
        deadline = time.monotonic() + timeout_seconds
        async with ResilientAuthoringClient(
            self.engine_base_url, self.engine_bearer
        ) as ec:
            tokens = {
                role: await self.mint(ec, f"agent:{self.run_id}:{role}", "agent")
                for role in self.case.roles
            }
            # One human principal is both the reviewer AND the operation-mode
            # policy setter (mode-set requires a human/system actor; a human
            # reviewer distinct from the agent author clears the self-approval ban).
            reviewer_human = await self.mint(ec, f"rev-human:{self.run_id}", "human")

            async with httpx.AsyncClient(headers=GATEWAY_AUTH_HEADERS) as hc:
                # Hardened run-start refusals (pure eligibility, no submit).
                await self.run_start(
                    hc,
                    run_id=f"{self.run_id}-no-feature",
                    tokens=tokens,
                    feature=None,
                    expect=422,
                )
                partial = {k: v for k, v in tokens.items() if k != self.case.roles[-1]}
                await self.run_start(
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
                await self.run_start(
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
                            _AutoGateContext(
                                gate=gate,
                                handled_changesets=handled_changesets,
                                poll_seconds=poll_seconds,
                                deadline=deadline,
                            ),
                        )
                    else:
                        await self._drive_human_gate(
                            ec,
                            hc,
                            _HumanGateContext(
                                gate=gate,
                                reviewer_token=reviewer_human,
                                handled=handled_proposals,
                                poll_seconds=poll_seconds,
                                deadline=deadline,
                            ),
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
                            and next_mode == MODE_MANUAL
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
                # A doc-authoring role must never have needed a non-read-only tool.
                assert not self._permission_violations, (
                    "non-read-only tool-permission request(s) by a doc-authoring "
                    f"role: {self._permission_violations}"
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


def reachable_stack() -> tuple[str, str, str, Path] | None:
    """Resolve (gateway_url, engine_base_url, engine_bearer, vault_root) or None.

    The gateway is resolved the way everything else on this machine is: the
    explicit environment override first, else the dev-process registry's LIVE,
    health-answering ``gateway-dev`` record - never a hardcoded band default,
    which concluded "no stack" whenever the port had been allocated rather
    than defaulted.
    """
    endpoint = resolve_engine()
    if endpoint is None:
        return None
    gateway = resolve_gateway_url()
    if gateway is None:
        return None
    service_json = os.environ.get("VAULTSPEC_A2A_ENGINE_SERVICE_JSON")
    if not service_json:
        return None
    vault_root = Path(service_json).parents[2]  # <ws>/.vault
    return gateway.url, endpoint.base_url, endpoint.bearer_token, vault_root


# ---------------------------------------------------------------------------
# Live observation toolkit
# ---------------------------------------------------------------------------

#: The preset and role of the bridged-authoring proofs, one per provider lane.
SOLO_CODER_PRESET = "vaultspec-solo-coder"
CODER_ROLE = "vaultspec-coder"

#: The qualified-name prefix every bridged engine authoring tool carries.
_BRIDGE_TOOL_PREFIX = "mcp__vaultspec-authoring__"

# The message frame types that carry an agent's mid-turn narration and output.
_MESSAGE_FRAMES = frozenset(
    {ServerEventType.MESSAGE_CHUNK.value, ServerEventType.THOUGHT_CHUNK.value}
)

# A live research turn takes minutes; bound the observation so a stalled run fails
# loud rather than hanging.
OBSERVE_DEADLINE_SECONDS = 900.0

# Cadence for polling the engine authoring plane for a run's changeset.
_ENGINE_POLL_SECONDS = 4.0

# The vaultspec DOCUMENT surface - the directories an agent-authored document would
# materialize under. The engine's own runtime tree (``.vault/data``: its sqlite DBs,
# WAL files, graph cache, and the heartbeat ``service.json``) churns continuously and
# is NOT an agent write, so it is excluded from the write watcher - a proof's "zero
# .vault writes" means zero agent-origin DOCUMENT writes (validated live: a
# whole-tree watcher tripped only on ``.vault/data`` engine churn).
_DOCUMENT_DIRS = ("adr", "research", "audit", "plan", "exec", "reference", "index")


def snapshot_vault(vault_root: Path) -> dict[str, tuple[float, int]]:
    """Map every agent-authorable document file to its (mtime, size).

    Scoped to the vaultspec document directories; the engine-owned ``.vault/data``
    runtime tree is excluded because its DB/WAL/heartbeat churn is not an agent write.
    """
    snapshot: dict[str, tuple[float, int]] = {}
    for doc_dir in _DOCUMENT_DIRS:
        base = vault_root / doc_dir
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[str(path)] = (stat.st_mtime, stat.st_size)
    return snapshot


def vault_write_delta(
    before: dict[str, tuple[float, int]], after: dict[str, tuple[float, int]]
) -> dict[str, list[str]]:
    """Return created/modified/deleted paths between two vault snapshots."""
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    return {"created": created, "modified": modified, "deleted": deleted}


def message_content(payload: Mapping[str, object]) -> str | None:
    """Return the content of a message/thought chunk frame, else None."""
    if payload.get("type") not in _MESSAGE_FRAMES:
        return None
    content = payload.get("content")
    return content if isinstance(content, str) else None


def _extract_bridge_tools(output: str) -> set[str]:
    """Return distinct ``mcp__vaultspec-authoring__<tool>`` names named in output."""
    tools: set[str] = set()
    idx = 0
    while True:
        found = output.find(_BRIDGE_TOOL_PREFIX, idx)
        if found == -1:
            break
        tail = output[found + len(_BRIDGE_TOOL_PREFIX) :]
        name = ""
        for ch in tail:
            if ch.isalnum() or ch == "_":
                name += ch
            else:
                break
        if name:
            tools.add(_BRIDGE_TOOL_PREFIX + name)
        idx = found + len(_BRIDGE_TOOL_PREFIX)
    return tools


async def _run_changeset_ids(ec: AuthoringClient, run_id: str) -> set[str]:
    """Return this run's changeset ids present in the engine authoring plane.

    A changeset id embeds the run id (``cs:<run_id>:<phase>-r<cycle>``), so a match
    is unforgeable proof the bridge forwarded a real ``propose_changeset`` to the
    engine. Scans every lane ``GET /authoring/v1/proposals`` exposes (the default
    ``items`` plus the ``applied_under_policy`` projection) so a proposal is found
    whatever verdict state it has reached.
    """
    resp = await ec.get("/v1/proposals", with_actor=False)
    data = json_object(resp.data, at="authoring proposals response")
    found: set[str] = set()
    lanes: list[object] = [data]
    applied = data.get("applied_under_policy")
    if applied is not None:
        applied_object = json_object(applied, at="authoring applied-under-policy lane")
        lanes.append(applied_object)
    for lane in lanes:
        for item in _items(lane, at="authoring proposal lane"):
            changeset = _dig(item, "changeset_id") or ""
            if run_id in changeset:
                found.add(changeset)
    return found


async def observe_bridged_authoring_run(
    ec: AuthoringClient,
    harness: AcceptanceHarness,
    gateway_client: httpx.AsyncClient,
    output_parts: list[str],
    narrated_bridge_names: set[str],
) -> set[str]:
    """Poll the engine during the run, then cancel the stream unconditionally.

    Returns the run's engine-side changeset ids - the proof a bridged authoring
    call landed. The narration it collects is diagnostic only: the prompt names
    the bridge tools itself, so a name merely spoken proves nothing.
    """
    deadline = time.monotonic() + OBSERVE_DEADLINE_SECONDS
    last_engine_poll = 0.0
    run_changesets: set[str] = set()
    try:
        async with gateway_client.stream(
            "GET",
            f"{harness.gateway_url}/v1/runs/{harness.run_id}/stream",
            timeout=httpx.Timeout(OBSERVE_DEADLINE_SECONDS, connect=10.0),
        ) as response:
            response.raise_for_status()
            async for event in iter_sse_events(response.aiter_lines()):
                payload = SseFrame.from_event(event).data
                content = message_content(payload)
                if content:
                    output_parts.append(content)
                    narrated_bridge_names.update(
                        _extract_bridge_tools("".join(output_parts))
                    )
                terminal = payload.get("type") == "thread_terminal"
                now = time.monotonic()
                # Poll the engine (not the narration) for this run's changeset.
                if now - last_engine_poll >= _ENGINE_POLL_SECONDS:
                    last_engine_poll = now
                    run_changesets = await _run_changeset_ids(ec, harness.run_id)
                if run_changesets or now > deadline:
                    break
                if terminal:
                    # Final authoritative check after the run settles.
                    run_changesets = await _run_changeset_ids(ec, harness.run_id)
                    break
    finally:
        await gateway_client.post(
            f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
            timeout=30.0,
        )
    return run_changesets
