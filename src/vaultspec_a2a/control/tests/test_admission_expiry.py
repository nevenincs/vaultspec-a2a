"""Capacity expiry invariants for the production admission state machine."""

import pytest

from ...control.admission import (
    AdmissionBroker,
    ReservationState,
    _Reservation,
)


def test_expired_uncertain_commit_releases_capacity() -> None:
    broker = AdmissionBroker(max_reservations=1)
    uncertain = _Reservation(
        reservation_id="resv-uncertain",
        lease_id="lease-uncertain",
        required_roles=("vaultspec-coder",),
        binding_digest="a" * 64,
        expires_monotonic=10.0,
        expires_at_iso="bounded",
        state=ReservationState.COMMITTING,
    )
    broker._reservations[uncertain.reservation_id] = uncertain

    broker._sweep_expired(10.001)

    assert uncertain.state is ReservationState.EXPIRED
    assert broker.active_reservation_count == 0


@pytest.mark.asyncio
async def test_release_uses_client_binding_not_canonical_commit_binding() -> None:
    broker = AdmissionBroker(max_reservations=1)
    reservation = _Reservation(
        reservation_id="resv-release",
        lease_id="lease-release",
        required_roles=("vaultspec-coder",),
        binding_digest="canonical-selection",
        release_digest="client-selection-with-omitted-default",
        expires_monotonic=10.0,
        expires_at_iso="bounded",
    )
    broker._reservations[reservation.reservation_id] = reservation

    assert not await broker.release(
        reservation.reservation_id, binding_digest="canonical-selection"
    )
    assert await broker.release(
        reservation.reservation_id,
        binding_digest="client-selection-with-omitted-default",
    )
    assert broker.active_reservation_count == 0


@pytest.mark.asyncio
async def test_failed_commit_cleanup_uses_canonical_binding() -> None:
    broker = AdmissionBroker(max_reservations=1)
    reservation = _Reservation(
        reservation_id="resv-refused-commit",
        lease_id="lease-refused-commit",
        required_roles=("vaultspec-coder",),
        binding_digest="canonical-selection",
        release_digest="client-selection-with-omitted-default",
        expires_monotonic=10.0,
        expires_at_iso="bounded",
    )
    broker._reservations[reservation.reservation_id] = reservation

    assert await broker.release_failed_commit(
        reservation.reservation_id, binding_digest="canonical-selection"
    )
    assert broker.active_reservation_count == 0
