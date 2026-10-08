"""A reservation carries its prepare's freeze to the commit that consumes it.

The two-stage protocol validates a run's provider selection ONCE, at prepare,
and the reservation's binding digest is the digest of that frozen result. These
hold the broker to handing that freeze back: a commit that recomputed it would
be re-answering a settled question against a catalog that may have moved, and
would refuse the exact request the reservation was issued for.

Real objects throughout: the production broker, the real frozen selection the
deterministic lane's served record produces, and real expiry on the loop clock -
no mock, no patched clock, no stub reservation.
"""

from __future__ import annotations

import pytest

from ...control.admission import AdmissionBroker, AdmissionReadiness
from ...control.readiness import ProviderEligibility, RunAdmission, WorkerLifecycleState
from ...testing import frozen_deterministic_selection

_ROLES = ("vaultspec-coder",)


def _execution_ready() -> AdmissionReadiness:
    """The readiness verdict a prepare must see to be admitted at all."""
    return AdmissionReadiness(
        worker_state=WorkerLifecycleState.READY,
        provider_eligibility=ProviderEligibility.ELIGIBLE,
        eligible_providers=("deterministic",),
        run_admission=RunAdmission.READY,
    )


async def _no_demand() -> None:
    """The worker this prepare needs is already up, so demand triggers nothing."""
    return None


async def _ready() -> AdmissionReadiness:
    return _execution_ready()


@pytest.mark.asyncio
async def test_a_prepared_reservation_hands_its_freeze_to_its_commit() -> None:
    """The freeze a prepare validated is the freeze its commit reads back."""
    broker = AdmissionBroker(max_reservations=1)
    frozen = frozen_deterministic_selection(_ROLES)

    outcome = await broker.prepare(
        required_roles=list(_ROLES),
        ensure_worker=_no_demand,
        probe_readiness=_ready,
        binding_digest="digest-over-the-frozen-request",
        frozen_selection=frozen,
    )

    assert outcome.admitted, outcome.reason
    assert outcome.reservation_id is not None
    assert await broker.admitted_selection(outcome.reservation_id) is frozen


@pytest.mark.asyncio
async def test_a_consumed_reservation_hands_over_no_freeze() -> None:
    """Once the durable run exists the reservation is gone, freeze and all."""
    broker = AdmissionBroker(max_reservations=1)
    outcome = await broker.prepare(
        required_roles=list(_ROLES),
        ensure_worker=_no_demand,
        probe_readiness=_ready,
        binding_digest="digest-over-the-frozen-request",
        frozen_selection=frozen_deterministic_selection(_ROLES),
    )
    assert outcome.reservation_id is not None and outcome.lease_id is not None

    assert await broker.complete_commit(outcome.reservation_id, outcome.lease_id)

    assert await broker.admitted_selection(outcome.reservation_id) is None


@pytest.mark.asyncio
async def test_an_expired_reservation_hands_over_no_freeze() -> None:
    """A lifetime of zero expires on the real clock, so the read refuses it.

    The same answer the commit itself would give, which is the point: a commit
    must not be admitted on a freeze its reservation no longer holds.
    """
    broker = AdmissionBroker(max_reservations=1, reservation_ttl_seconds=0.0)
    outcome = await broker.prepare(
        required_roles=list(_ROLES),
        ensure_worker=_no_demand,
        probe_readiness=_ready,
        binding_digest="digest-over-the-frozen-request",
        frozen_selection=frozen_deterministic_selection(_ROLES),
    )
    assert outcome.reservation_id is not None

    assert await broker.admitted_selection(outcome.reservation_id) is None
    assert broker.active_reservation_count == 0
