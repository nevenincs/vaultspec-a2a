"""Capacity expiry invariants for the production admission state machine."""

from vaultspec_a2a.control.admission import (
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
