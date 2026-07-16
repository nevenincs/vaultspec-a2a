"""Unit tests for the run-start eligibility policy.

Pure logic over real ``TeamConfig`` objects loaded from the bundled presets and a
real ``ActorTokenBundle`` - no mocks. The document-authoring preset is
``vaultspec-adr-research`` (research_adr topology); ``mock-success-single`` is a
non-authoring coder preset.
"""

from __future__ import annotations

from vaultspec_a2a.context.harness import HarnessReadiness
from vaultspec_a2a.control.run_start_policy import (
    evaluate_run_start_eligibility,
    is_document_authoring_preset,
    required_role_ids,
)
from vaultspec_a2a.team.team_config import load_team_config
from vaultspec_a2a.thread.actor_tokens import ActorTokenBundle

_AUTHORING = "vaultspec-adr-research"
_CODER = "mock-success-single"
_AUTHORING_ROLES = (
    "vaultspec-researcher",
    "vaultspec-synthesist",
    "vaultspec-adr-author",
    "vaultspec-doc-reviewer",
)


def _full_bundle() -> ActorTokenBundle:
    return ActorTokenBundle(
        tokens={role: f"tok-{role}" for role in _AUTHORING_ROLES},
        engine_bearer="bearer",
    )


def test_research_adr_is_document_authoring() -> None:
    assert is_document_authoring_preset(load_team_config(_AUTHORING)) is True


def test_coder_preset_is_not_document_authoring() -> None:
    assert is_document_authoring_preset(load_team_config(_CODER)) is False


def test_required_role_ids_are_the_worker_agent_ids() -> None:
    assert required_role_ids(load_team_config(_AUTHORING)) == list(_AUTHORING_ROLES)


def test_authoring_preset_is_eligible_with_feature_and_full_bundle() -> None:
    result = evaluate_run_start_eligibility(
        load_team_config(_AUTHORING),
        feature_tag="my-feature",
        actor_tokens=_full_bundle(),
    )
    assert result.eligible is True
    assert result.reason is None


def test_authoring_preset_without_feature_is_ineligible() -> None:
    result = evaluate_run_start_eligibility(
        load_team_config(_AUTHORING),
        feature_tag=None,
        actor_tokens=_full_bundle(),
    )
    assert result.eligible is False
    assert "target feature" in (result.reason or "")


def test_authoring_preset_with_incomplete_bundle_is_ineligible() -> None:
    partial = ActorTokenBundle(
        tokens={"vaultspec-researcher": "tok-r"}, engine_bearer="bearer"
    )
    result = evaluate_run_start_eligibility(
        load_team_config(_AUTHORING),
        feature_tag="my-feature",
        actor_tokens=partial,
    )
    assert result.eligible is False
    assert "missing a token" in (result.reason or "")
    # The specific unmet roles are named, the present one is not flagged.
    assert "vaultspec-synthesist" in (result.reason or "")


def test_authoring_preset_with_no_bundle_is_ineligible() -> None:
    result = evaluate_run_start_eligibility(
        load_team_config(_AUTHORING),
        feature_tag="my-feature",
        actor_tokens=None,
    )
    assert result.eligible is False
    assert "missing a token" in (result.reason or "")


def test_coder_preset_is_eligible_without_feature_or_tokens() -> None:
    result = evaluate_run_start_eligibility(
        load_team_config(_CODER),
        feature_tag=None,
        actor_tokens=None,
    )
    assert result.eligible is True


def test_incomplete_harness_refuses_an_otherwise_eligible_authoring_run() -> None:
    result = evaluate_run_start_eligibility(
        load_team_config(_AUTHORING),
        feature_tag="my-feature",
        actor_tokens=_full_bundle(),
        harness=HarnessReadiness(
            ready=False,
            reasons=["rules corpus is empty or absent (.vaultspec/rules)"],
        ),
    )
    assert result.eligible is False
    assert "agent harness incomplete" in (result.reason or "")
    assert "rules corpus" in (result.reason or "")


def test_ready_harness_leaves_authoring_run_eligible() -> None:
    result = evaluate_run_start_eligibility(
        load_team_config(_AUTHORING),
        feature_tag="my-feature",
        actor_tokens=_full_bundle(),
        harness=HarnessReadiness(ready=True),
    )
    assert result.eligible is True
    assert result.reason is None


def test_harness_is_not_enforced_on_non_authoring_presets() -> None:
    """A coder preset never gates on harness, even with a broken verdict."""
    result = evaluate_run_start_eligibility(
        load_team_config(_CODER),
        feature_tag=None,
        actor_tokens=None,
        harness=HarnessReadiness(ready=False, reasons=["rules corpus absent"]),
    )
    assert result.eligible is True
