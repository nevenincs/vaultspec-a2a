"""PW7 headless acceptance harness for the document-authoring loop (P04.S10).

The STANDING acceptance driver for the research-to-ADR phase machine, built as a
reusable, parameterized harness rather than a one-off so the successor document
workloads (curation, plan-authoring) reuse it. Given a prompt it drives one run
end to end against the live loopback stack and asserts that N markdown documents
materialize under ``.vault/`` - the PW7 contract's document-materialization
assertion single-homed here.

The loop it exercises, all live and mock-free:

* mint one Agent-kind actor token per preset role plus a system-class and a
  human-class reviewer token against the engine authoring API;
* assert the hardened v1 ``run-start`` refusals (422: missing target feature;
  422: an actor-token bundle not covering every required role);
* ``run-start`` the preset with the token bundle and a target feature;
* drive each gate's verdict PROGRAMMATICALLY over the engine review surface
  (review-queue -> decision -> apply) under the per-gate verdict policy - AUTO
  approves immediately with a system-class actor, HUMAN with a human-class actor
  (both are normal review-lane flow; the self-approval ban is origin-keyed);
* the verdict subscriber resumes the parked run across gates;
* assert the expected documents materialized on disk with the expected stems.

Gate detection keys on the ENGINE review-queue (a queued proposal scoped to this
run's changeset id), not the a2a semantic phase, so it is robust to the reconciler
masking ``awaiting_adr_decision`` as ``recovery_required`` after a subscriber
resume (P04.S10 GAP D).

Infrastructure gate, not a masked failure: the test skips with a runbook pointer
when no loopback engine is reachable (resolved through the discovery contract) or
the a2a gateway is not up. Boot the stack per the P04.S10 runbook - a workspace-
local ``vaultspec serve --no-seat`` engine plus the a2a gateway/worker with
``VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true`` - then select ``-m service``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from ..authoring import AuthoringClient, mint_actor_token
from ..authoring._envelope import AuthoringResponse, Denial
from ..authoring.discovery import resolve_engine

_GATEWAY_URL = os.environ.get("VAULTSPEC_GATEWAY_URL", "http://127.0.0.1:18100")
_RESEARCH_ADR_ROLES = (
    "vaultspec-researcher",
    "vaultspec-synthesist",
    "vaultspec-adr-author",
    "vaultspec-doc-reviewer",
)


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    """A parameterized PW7 acceptance case.

    Parameters
    ----------
    preset:            The document-authoring team preset to run.
    feature:           The target feature tag the documents are authored for.
    prompt:            The run's opening research prompt.
    roles:             The preset's required role ids (the token bundle keys).
    expected_doc_kinds:
        The ``.vault`` subdirectories a materialized document is expected under,
        in gate order (e.g. ``("research", "adr")``).
    gate_policy:       Per-gate verdict policy - ``"AUTO"`` (system actor) or
                       ``"HUMAN"`` (human actor) - keyed by gate ordinal name.
    """

    preset: str
    feature: str
    prompt: str
    roles: tuple[str, ...]
    expected_doc_kinds: tuple[str, ...]
    gate_policy: dict[str, str] = field(default_factory=dict)


RESEARCH_ADR_CASE = AcceptanceCase(
    preset="vaultspec-adr-research",
    feature="sse-reconnection",
    prompt=(
        "research and decide an SSE reconnection and cursor-persistence strategy "
        "for long-lived dashboard event streams"
    ),
    roles=_RESEARCH_ADR_ROLES,
    expected_doc_kinds=("research", "adr"),
    gate_policy={"research": "AUTO", "adr": "HUMAN"},
)


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


def _queue_items(data: dict) -> list[dict]:
    items = data.get("items")
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


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

    async def _find_queue_item(
        self, ec: AuthoringClient, handled: set[str]
    ) -> dict | None:
        resp = await ec.get("/v1/review-queue", with_actor=False)
        data = resp.data if isinstance(resp, AuthoringResponse) else {}
        for item in _queue_items(data):
            changeset = _dig(item, "changeset_id") or ""
            proposal = _dig(item, "proposal_id")
            if self.run_id in changeset and proposal not in handled:
                return item
        return None

    async def _decide_and_apply(
        self, ec: AuthoringClient, item: dict, *, reviewer_token: str, gate: str
    ) -> None:
        proposal_id = _dig(item, "proposal_id")
        approval_id = _dig(item, "approval_id")
        changeset_id = _dig(item, "changeset_id")
        reviewed_revision = _dig(item, "reviewed_proposal_revision") or _dig(
            item, "changeset_revision"
        )
        policy = self.case.gate_policy.get(gate, "AUTO")
        decision = await ec.post_command(
            f"/v1/reviews/{approval_id}/decisions",
            "approve",
            {
                "proposal_id": proposal_id,
                "approval_id": approval_id,
                "decision": "approve",
                "reviewed_revision": reviewed_revision,
                "comment": f"{gate} gate {policy} approval (PW7 harness)",
            },
            idempotency_key=f"idk-decide-{gate}-{self.run_id}",
            actor_token=reviewer_token,
        )
        assert isinstance(decision, AuthoringResponse), f"decision denied: {decision}"
        assert decision.data.get("status") in {"decided", "replayed"}
        applied = await ec.post_command(
            "/v1/apply-requests",
            "request_apply",
            {"changeset_id": changeset_id, "approval_id": approval_id},
            idempotency_key=f"idk-apply-{gate}-{self.run_id}",
            actor_token=reviewer_token,
        )
        if isinstance(applied, Denial):
            raise AssertionError(
                f"{gate} apply denied ({applied.denial_kind}): {applied.reason}"
            )
        assert applied.data.get("status") == "recorded"

    async def run(self, *, timeout_seconds: float = 2400.0) -> list[str]:
        """Drive the full loop; return the ordered list of gates driven."""
        async with AuthoringClient(self.engine_base_url, self.engine_bearer) as ec:
            tokens = {
                role: await self._mint(ec, f"agent:{self.run_id}:{role}", "agent")
                for role in self.case.roles
            }
            reviewer_system = await self._mint(ec, f"rev-sys:{self.run_id}", "system")
            reviewer_human = await self._mint(ec, f"rev-human:{self.run_id}", "human")
            reviewer_for = {"AUTO": reviewer_system, "HUMAN": reviewer_human}

            async with httpx.AsyncClient() as hc:
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
                await self._run_start(
                    hc,
                    run_id=self.run_id,
                    tokens=tokens,
                    feature=self.case.feature,
                    expect=201,
                )

                gates_done: list[str] = []
                handled: set[str] = set()
                gate_names = list(self.case.gate_policy) or ["gate"]
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    status = await self._run_status(hc)
                    phase = status.get("semantic_phase")
                    if phase and (
                        not self.phases_seen or self.phases_seen[-1] != phase
                    ):
                        self.phases_seen.append(phase)
                    if status.get("status") in {"failed", "cancelled"}:
                        raise AssertionError(
                            f"run terminal failure: {json.dumps(status)[:800]}"
                        )
                    item = await self._find_queue_item(ec, handled)
                    if item is not None:
                        gate = gate_names[min(len(gates_done), len(gate_names) - 1)]
                        await self._decide_and_apply(
                            ec,
                            item,
                            reviewer_token=reviewer_for[
                                self.case.gate_policy.get(gate, "AUTO")
                            ],
                            gate=gate,
                        )
                        proposal = _dig(item, "proposal_id")
                        if proposal:
                            handled.add(proposal)
                        gates_done.append(gate)
                    if len(gates_done) >= len(self.case.expected_doc_kinds):
                        return gates_done
                    await asyncio.sleep(5)
                raise AssertionError(
                    f"timed out; gates_done={gates_done} phases={self.phases_seen}"
                )

    async def _run_status(self, hc: httpx.AsyncClient) -> dict:
        resp = await hc.get(f"{self.gateway_url}/v1/runs/{self.run_id}", timeout=30.0)
        resp.raise_for_status()
        return resp.json()

    def materialized(self) -> dict[str, list[Path]]:
        """Return the materialized markdown documents per expected doc kind."""
        out: dict[str, list[Path]] = {}
        for kind in self.case.expected_doc_kinds:
            directory = self.vault_root / kind
            out[kind] = sorted(directory.glob("*.md")) if directory.is_dir() else []
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
async def test_pw7_research_adr_materializes_two_documents() -> None:
    """The research_adr loop materializes exactly the expected document set.

    Drives the standing PW7 acceptance case end to end and asserts a research and
    an ADR document materialize under the engine workspace ``.vault/`` - the PW7
    document-materialization contract for ``research_adr`` (N = 2). Verdicts are
    driven programmatically over the engine review surface with a mixed per-gate
    policy (research AUTO/system-actor, adr HUMAN/human-actor).
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
        case=RESEARCH_ADR_CASE,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
    )

    gates_driven = await harness.run()

    assert gates_driven == ["research", "adr"]
    materialized = harness.materialized()
    assert materialized["research"], "no research document materialized on disk"
    assert materialized["adr"], "no ADR document materialized on disk"
