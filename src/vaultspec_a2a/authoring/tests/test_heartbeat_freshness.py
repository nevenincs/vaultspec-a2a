"""A present-but-unusable heartbeat must read as stale, never as fresh.

This guard decides whether a peer is treated as running, so its failure
direction is the whole point. It previously returned fresh for anything it could
not parse, which meant a record claiming an infinite or far-future heartbeat read
as permanently live - exactly the shape a stale or forged record takes.

Absence still means fresh, because the field is optional per the contract and its
absence says nothing about liveness. Presence is what must be judged.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ..discovery import HEARTBEAT_STALE_MS, heartbeat_is_fresh

_NOW = int(datetime(2027, 1, 15, 8, 0, 0, tzinfo=UTC).timestamp() * 1000)


def test_an_absent_heartbeat_is_fresh() -> None:
    """The field is optional; its absence is not evidence of a crash."""
    assert heartbeat_is_fresh({}, _NOW) is True


def test_an_explicit_null_heartbeat_is_fresh() -> None:
    """A JSON null is equivalent to the field being omitted."""
    assert heartbeat_is_fresh({"last_heartbeat": None}, _NOW) is True


def test_a_recent_heartbeat_is_fresh() -> None:
    """Inside the window is the ordinary live case."""
    assert heartbeat_is_fresh({"last_heartbeat": _NOW - 1000}, _NOW) is True


def test_a_heartbeat_older_than_the_window_is_stale() -> None:
    """Beyond the window reads as a crash."""
    stale = _NOW - HEARTBEAT_STALE_MS - 1

    assert heartbeat_is_fresh({"last_heartbeat": stale}, _NOW) is False


def test_an_infinite_heartbeat_is_stale_not_permanently_fresh() -> None:
    """The defect this guard most needed closed: infinity licensed liveness forever."""
    assert heartbeat_is_fresh({"last_heartbeat": float("inf")}, _NOW) is False


@pytest.mark.parametrize("value", [float("nan"), float("-inf")])
def test_other_non_finite_values_are_stale(value: float) -> None:
    """No non-finite value can describe a real instant."""
    assert heartbeat_is_fresh({"last_heartbeat": value}, _NOW) is False


def test_an_implausibly_future_heartbeat_is_stale() -> None:
    """A far-future timestamp would otherwise pin freshness indefinitely."""
    assert heartbeat_is_fresh({"last_heartbeat": _NOW + 10**12}, _NOW) is False


def test_modest_clock_skew_into_the_future_is_tolerated() -> None:
    """Peers disagree slightly; one window of skew is absorbed rather than punished."""
    slightly_ahead = _NOW + (HEARTBEAT_STALE_MS // 2)

    assert heartbeat_is_fresh({"last_heartbeat": slightly_ahead}, _NOW) is True


@pytest.mark.parametrize(
    "value",
    [
        "2027-01-15T08:00:00Z",
        "2027-01-15T08:00:00",
        "2027-01-15T09:00:00+01:00",
    ],
    ids=["zulu", "naive", "offset"],
)
def test_an_iso_heartbeat_is_parsed(value: str) -> None:
    """A peer may publish ISO rather than a number; both describe the same instant."""
    assert heartbeat_is_fresh({"last_heartbeat": value}, _NOW) is True


def test_a_stale_iso_heartbeat_is_stale() -> None:
    """ISO parsing must not become a way to bypass the window."""
    assert heartbeat_is_fresh({"last_heartbeat": "2027-01-15T07:50:00Z"}, _NOW) is False


@pytest.mark.parametrize(
    "value", ["not-a-time", "", "   ", True, False, {}, [], object()]
)
def test_an_unusable_present_heartbeat_is_stale(value: object) -> None:
    """Anything present that cannot be read as an instant fails closed."""
    assert heartbeat_is_fresh({"last_heartbeat": value}, _NOW) is False
