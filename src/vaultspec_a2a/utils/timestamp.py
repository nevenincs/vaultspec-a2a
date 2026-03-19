"""UTC timestamp utilities — standard library only."""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["human_delta", "now_utc", "parse_iso"]

_MINUTE = 60
_HOUR = _MINUTE * 60
_DAY = _HOUR * 24


def now_utc() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string and return a timezone-aware datetime.

    Python 3.11+ ``datetime.fromisoformat`` handles the full ISO 8601
    format including the trailing ``Z`` suffix.
    """
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def human_delta(dt: datetime) -> str:
    """Return a human-readable relative-time string for *dt*.

    Examples::

        human_delta(two_minutes_ago)   # "2 minutes ago"
        human_delta(one_hour_ago)      # "1 hour ago"

    Future datetimes are described with "in X …" phrasing.  The
    reference point is always ``datetime.now(timezone.utc)``.
    """
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    delta = now - dt
    total = delta.total_seconds()
    future = total < 0
    total = abs(total)

    if total < _MINUTE:
        n = int(total)
        unit = "second" if n == 1 else "seconds"
        label = f"{n} {unit}"
    elif total < _HOUR:
        n = int(total // _MINUTE)
        unit = "minute" if n == 1 else "minutes"
        label = f"{n} {unit}"
    elif total < _DAY:
        n = int(total // _HOUR)
        unit = "hour" if n == 1 else "hours"
        label = f"{n} {unit}"
    else:
        n = int(total // _DAY)
        unit = "day" if n == 1 else "days"
        label = f"{n} {unit}"

    return f"in {label}" if future else f"{label} ago"
