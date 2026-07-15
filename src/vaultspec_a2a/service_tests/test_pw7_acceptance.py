"""PW7 headless acceptance harness for the document-authoring loop (P04.S10).

The STANDING acceptance driver for the research-to-ADR phase machine, built as a
reusable, parameterized harness rather than a one-off so the successor document
workloads (curation, plan-authoring) reuse it. Given a prompt it drives one run
end to end against the live loopback stack and asserts that N markdown documents
materialize under ``.vault/`` - the PW7 contract's document-materialization
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

Gate detection keys on the ENGINE surface (a queued proposal / an applied-under-
policy marker scoped to this run's changeset id ``cs:<run_id>:<phase>-r<cycle>``),
not the a2a semantic phase, so it is robust to the reconciler masking the semantic
phase after a subscriber resume (P04.S10 GAP D).

Wire shapes are grounded in the engine Rust source (read-only), not this brief's
prose: ``ReviewDecisionRequest`` (``decision`` enum ``approve|reject|edit|respond``,
load-bearing ``reviewed_revision``), ``ApplyRequest`` (``changeset_id`` +
``approval_id``), ``SetOperationModeRequest`` (``mode`` enum
``manual|assisted|autonomous``, human/system actor only), the apply receipt's
``child.{document_path,result_stem,outcome}``, and the ``applied_under_policy``
projection lane carrying ``system_actor`` / ``mode`` / ``policy_id``.

Infrastructure gate, not a masked failure: the test skips with a runbook pointer
when no loopback engine is reachable (resolved through the discovery contract) or
the a2a gateway is not up. Boot the stack per the P04.S10 runbook - a workspace-
local ``vaultspec serve --no-seat`` engine plus the a2a gateway/worker with
``VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true`` - then select ``-m service``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from ..authoring import AuthoringClient, mint_actor_token
from ..authoring._envelope import AuthoringResponse, Denial
from ..authoring._errors import AuthoringTransportError
from ..authoring.discovery import resolve_engine

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
# `/v1/reviews/{approval_id}/decisions` route requires. The route is registered
# under a SINGLE CommandKind — `Approve` (engine `api/mod.rs` RouteFixture,
# `path_template: ".../decisions"`, `command: Some(CommandKind::Approve)`);
# approve / reject / edit are distinguished by the `decision` field in the
# ReviewDecisionRequest payload, NOT by the envelope command. (There is no
# `submit_review_decision` CommandKind — that is the handler fn name, not a
# wire command.)
_REVIEW_DECISION_COMMAND = "approve"

# The system auto-approval actor id + policy id the operation-modes machinery
# stamps on a `SystemPolicyApprovalRecord` (engine `modes.rs`
# `SYSTEM_AUTO_APPROVER_ID` / `MODE_POLICY_ID`). The AUTO lane asserts these
# exactly - the anti-bypass invariant - never a human decision record.
_SYSTEM_AUTO_APPROVER_ID = "system:operation-modes"
_MODE_POLICY_ID = "authoring.operation_modes"

# The two research_adr driver presets. DETERMINISTIC is opus-6's in-process
# Provider.DETERMINISTIC device (commits 4a66cb2 + 49772bc): the fast,
# provider-agnostic Option A lane run on every dispatch. LIVE is the parallel
# session's original real-Claude preset (6deb9a8): the Option C real-provider
# proof, run once after the Option A lanes are green, select it with `-k live`.
_PRESET_DETERMINISTIC = "vaultspec-adr-research-deterministic"
_PRESET_LIVE = "vaultspec-adr-research"


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    """A parameterized PW7 acceptance case.

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
    """

    label: str
    preset: str
    feature: str
    prompt: str
    roles: tuple[str, ...]
    expected_doc_kinds: tuple[str, ...]
    gate_policy: dict[str, str] = field(default_factory=dict)


def _research_adr_case(
    label: str,
    feature: str,
    gate_policy: dict[str, str],
    *,
    preset: str = _PRESET_DETERMINISTIC,
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
    )


# The lane matrix. The three deterministic (Option A) lanes are the fast,
# provider-agnostic default run on every dispatch; each is a distinct claim
# (re-dispatch reference "exercise all three, not just one"), MIXED being the
# per-gate-granularity proof. The `live` case is the same MIXED shape against the
# real-Claude preset - the Option C real-provider proof - carrying `live` in its
# id so `-k "not live"` runs the fast lanes and `-k live` runs Option C alone.
CASE_AUTO = _research_adr_case(
    "auto", "sse-reconnection-auto", {"research": POLICY_AUTO, "adr": POLICY_AUTO}
)
CASE_HUMAN = _research_adr_case(
    "human", "sse-reconnection-human", {"research": POLICY_HUMAN, "adr": POLICY_HUMAN}
)
CASE_MIXED = _research_adr_case(
    "mixed", "sse-reconnection-mixed", {"research": POLICY_AUTO, "adr": POLICY_HUMAN}
)
CASE_LIVE_MIXED = _research_adr_case(
    "live-mixed",
    "sse-reconnection-live",
    {"research": POLICY_AUTO, "adr": POLICY_HUMAN},
    preset=_PRESET_LIVE,
)

_ALL_CASES = (CASE_AUTO, CASE_HUMAN, CASE_MIXED, CASE_LIVE_MIXED)


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


@dataclass(slots=True)
class AcceptanceHarness:
    """Drives one PW7 acceptance case against the live loopback stack."""

    case: AcceptanceCase
    engine_base_url: str
    engine_bearer: str
    vault_root: Path
    gateway_url: str = _GATEWAY_URL
    run_id: str = field(default_factory=lambda: f"pw7-{int(time.time())}")
    phases_seen: list[str] = field(default_factory=list)
    materializations: list[Materialization] = field(default_factory=list)
    _idk_counter: itertools.count = field(default_factory=lambda: itertools.count())
    _current_mode: str | None = None

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
            "profile_id": "team-defaults",
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
        resp = await hc.get(f"{self.gateway_url}/v1/runs/{self.run_id}", timeout=30.0)
        resp.raise_for_status()
        return resp.json()

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
            _REVIEW_DECISION_COMMAND,
            {
                "proposal_id": proposal_id,
                "approval_id": approval_id,
                "decision": decision,
                "reviewed_revision": reviewed_revision,
                "comment": f"{gate} gate {decision} (PW7 harness)",
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
                _REVIEW_DECISION_COMMAND,
                {
                    "proposal_id": proposal_id,
                    "approval_id": approval_id,
                    "decision": _DECISION_APPROVE,
                    "reviewed_revision": "blob:pw7stalefence0000",
                    "comment": f"{gate} stale-revision fence probe (PW7 harness)",
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

    async def run(
        self, *, timeout_seconds: float = 2400.0, poll_seconds: float = 5.0
    ) -> list[str]:
        """Drive the full loop; return the ordered list of gates driven."""
        gate_names = list(self.case.gate_policy) or ["gate"]
        deadline = time.monotonic() + timeout_seconds
        async with AuthoringClient(self.engine_base_url, self.engine_bearer) as ec:
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
                    feature=self.case.feature,
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
                    feature=self.case.feature,
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
                sorted(directory.glob(f"*{self.case.feature}*.md"))
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
@pytest.mark.parametrize("case", _ALL_CASES, ids=[c.label for c in _ALL_CASES])
async def test_pw7_research_adr_materializes_two_documents(
    case: AcceptanceCase,
) -> None:
    """The research_adr loop materializes exactly the expected document set.

    Drives the standing PW7 acceptance case end to end and asserts a research and
    an ADR document materialize under the engine workspace ``.vault/`` - the PW7
    document-materialization contract for ``research_adr`` (N = 2) - across the
    three verdict lanes (HUMAN reject-with-notes -> revision -> approve; AUTO
    operation-modes system approval; MIXED per-gate). Verdicts are driven
    programmatically over the engine surface.
    """
    stack = _reachable_stack()
    if stack is None:
        pytest.skip(
            "no reachable loopback stack; boot a workspace-local `vaultspec serve "
            "--no-seat` engine plus the a2a gateway/worker with "
            "VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true (P04.S10 runbook), then "
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
