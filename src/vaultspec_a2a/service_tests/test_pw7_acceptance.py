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
the a2a gateway is not up. Boot the stack per the runbook - a workspace-local
``vaultspec serve --no-seat`` engine whose discovery record the a2a gateway can
read (that record is what runs the verdict subscriber), plus the a2a
gateway/worker - then select ``-m service``.

The one stack-free test here pins the lane matrix's own timeout marking against the
harness's runtime budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..control.run_start_policy import required_role_ids
from ..team.team_config import load_team_config
from ..testing import (
    POLICY_AUTO,
    POLICY_HUMAN,
    PRESET_DETERMINISTIC,
    PRESET_LIVE,
    AcceptanceCase,
    AcceptanceHarness,
    is_live_lane,
    reachable_stack,
    resolve_selection,
    runtime_budget_for,
)

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet

    from ..conftest import ExternalPrerequisiteRule

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
