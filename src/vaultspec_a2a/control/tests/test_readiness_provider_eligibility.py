"""Provider eligibility is derived once, and never on the event loop.

Deriving the fact is the one readiness step that can SPAWN: the served-lane
predicate resolves each proven lane's launcher and runs a bounded ``--version``
child for an identity it has not seen before. The readiness authority therefore
takes the verdict the same way it takes the live database and worker verdicts -
from the caller that already has it - so an async surface can compute it in a
worker thread while the synchronous surfaces still derive it themselves.

Real objects: the real readiness authority over a plain app-state carrier, the
real derivation behind it, and that derivation's own version-report cache.
"""

from __future__ import annotations

from ...providers.binary_version import _reported_version
from ..health import _eligible_provider_names, assemble_desktop_readiness
from ..readiness import ProviderEligibility, RunAdmission


class _AppState:
    """The seated attributes the readiness authority reads, and nothing else."""

    db_engine = None


def test_the_authority_serves_the_eligibility_verdict_it_is_handed() -> None:
    """A caller that already derived the fact is not made to derive it twice."""
    readiness = assemble_desktop_readiness(
        app_state=_AppState(), eligible_providers=["codex"]
    )

    assert readiness.provider_eligibility is ProviderEligibility.ELIGIBLE
    assert readiness.eligible_providers == ["codex"]


def test_an_empty_handed_verdict_is_a_verdict_not_a_missing_one() -> None:
    """``[]`` means no lane is eligible; only ``None`` asks for a derivation.

    The distinction is load-bearing: a host whose lanes are all ineligible must
    not have the authority quietly re-derive the fact and spawn the version
    probes the caller moved off the loop precisely to avoid.
    """
    readiness = assemble_desktop_readiness(app_state=_AppState(), eligible_providers=[])

    assert readiness.provider_eligibility is ProviderEligibility.INELIGIBLE
    assert readiness.eligible_providers == []
    assert readiness.run_admission is not RunAdmission.READY
    assert readiness.reasons


def test_the_derivation_is_stable_and_costs_one_probe_per_launch_identity() -> None:
    """Two derivations agree, and the second spawns no version child.

    This is the measurement behind the claim the readiness surfaces make: the
    launcher version report is cached per launch identity, failures included, so
    a lane costs at most one bounded ``--version`` child per process. That is
    what makes the cost worth moving to a worker thread once rather than being
    cached a second time here. Read through the cache's own counters, because the
    claim is about the child actually running, not about the verdict; a host that
    serves no proven lane probes nothing and the counters simply do not move.
    """
    first = _eligible_provider_names()
    probes = _reported_version.cache_info().misses

    second = _eligible_provider_names()

    assert second == first
    assert _reported_version.cache_info().misses == probes
