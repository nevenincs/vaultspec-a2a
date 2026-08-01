"""What discovery advertises as required roles is what run-start enforces.

A caller mints one actor token per role from the list ``presets-list`` serves, and
run-start then refuses a bundle that misses any required role. Those two lists
must be the same list. If they ever drift apart the failure is silent and total:
the caller mints exactly what it was told, run-start refuses for a role that was
never advertised, and the refusal lands in the eligibility gate BEFORE any
dispatch - so the graph never runs, no worker starts, and every downstream test
that exercises the graph keeps passing while no real run can begin at all.

That is why these assert the identity rather than a snapshot of today's roles: a
list of expected role names here would go stale the moment a preset gains a role,
which is precisely the drift being guarded. The red-turning input is a second
derivation of "required roles" appearing anywhere - the discovery surface once
hand-rolled its own comprehension, agreeing with the policy by coincidence rather
than by construction.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ...control.run_start_policy import (
    evaluate_run_start_eligibility,
    required_role_ids,
)
from ...team.team_config import discover_team_preset_ids, load_team_config
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.errors import ConfigError
from ..routes.gateway import _summarize_preset


def _real_preset_ids() -> list[str]:
    """Every bundled preset that loads, mocks included - they dispatch too."""
    ids = []
    for preset_id in sorted(discover_team_preset_ids()):
        try:
            load_team_config(preset_id)
        except (ConfigError, ValidationError):
            # An unloadable preset has no role contract to check; discovery's
            # handling of it is proven separately.
            continue
        ids.append(preset_id)
    return ids


@pytest.mark.parametrize("preset_id", _real_preset_ids())
def test_discovery_advertises_exactly_the_roles_policy_requires(preset_id: str) -> None:
    """Red if the served list and the enforced list are computed separately."""
    tc = load_team_config(preset_id)

    summary = _summarize_preset(preset_id, None, False)

    assert list(summary.required_roles) == required_role_ids(tc), (
        f"preset {preset_id!r} advertises required_roles that differ from the "
        "roles run-start enforces; a caller minting the advertised set would be "
        "refused before dispatch"
    )


@pytest.mark.parametrize("preset_id", _real_preset_ids())
def test_a_bundle_minted_from_discovery_is_never_refused_for_missing_roles(
    preset_id: str,
) -> None:
    """The behavioural half: mint what is advertised, and run-start must not refuse.

    Asserting the lists match proves they agree; this proves agreeing is
    sufficient. A caller that does exactly what discovery tells it gets past the
    token gate, so any refusal here names a different cause (a feature tag, the
    harness) and never a role the caller could not have known to mint.
    """
    tc = load_team_config(preset_id)
    summary = _summarize_preset(preset_id, None, False)

    bundle = ActorTokenBundle(
        tokens={role: f"tok-{role}" for role in summary.required_roles},
        engine_bearer="bearer",
    )
    verdict = evaluate_run_start_eligibility(
        tc,
        feature_tag="role-contract",
        actor_tokens=bundle,
        harness=None,
    )

    reason = verdict.reason or ""
    assert "missing a token" not in reason and "missing an actor token" not in reason, (
        f"preset {preset_id!r} refused a bundle minted from its own advertised "
        f"required_roles: {reason}"
    )
