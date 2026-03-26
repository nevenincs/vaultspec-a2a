"""Tests for timestamp utilities.

All assertions derive from the specification — no mocks or monkeypatching.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ..timestamp import human_delta, now_utc, parse_iso

# ---------------------------------------------------------------------------
# now_utc
# ---------------------------------------------------------------------------


class TestNowUtc:
    """now_utc() returns a well-formed, timezone-aware ISO 8601 string."""

    def test_returns_string(self) -> None:
        result = now_utc()
        assert isinstance(result, str)

    def test_parseable_and_utc(self) -> None:
        result = now_utc()
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None
        offset = dt.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0

    def test_approximately_current_time(self) -> None:
        before = datetime.now(UTC)
        result = now_utc()
        after = datetime.now(UTC)
        dt = datetime.fromisoformat(result)
        assert before <= dt <= after


# ---------------------------------------------------------------------------
# parse_iso
# ---------------------------------------------------------------------------


class TestParseIso:
    """parse_iso() converts ISO 8601 strings to timezone-aware datetimes."""

    def test_roundtrip_with_offset(self) -> None:
        original = datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)
        s = original.isoformat()
        parsed = parse_iso(s)
        assert parsed == original

    def test_z_suffix(self) -> None:
        parsed = parse_iso("2024-01-01T00:00:00Z")
        assert parsed.tzinfo is not None
        assert parsed.year == 2024
        assert parsed.month == 1
        assert parsed.day == 1

    def test_naive_string_assumed_utc(self) -> None:
        parsed = parse_iso("2025-03-19T10:00:00")
        assert parsed.tzinfo == UTC

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_iso("not-a-date")


# ---------------------------------------------------------------------------
# human_delta
# ---------------------------------------------------------------------------


class TestHumanDelta:
    """human_delta() returns human-friendly relative-time strings."""

    def _ago(self, **kwargs: int) -> datetime:
        return datetime.now(UTC) - timedelta(**kwargs)

    def _ahead(self, **kwargs: int) -> datetime:
        return datetime.now(UTC) + timedelta(**kwargs)

    def test_seconds_ago(self) -> None:
        result = human_delta(self._ago(seconds=30))
        assert result.endswith("ago")
        assert "second" in result

    def test_minutes_ago(self) -> None:
        result = human_delta(self._ago(minutes=5))
        assert result == "5 minutes ago"

    def test_singular_minute(self) -> None:
        result = human_delta(self._ago(seconds=90))
        assert result == "1 minute ago"

    def test_hours_ago(self) -> None:
        result = human_delta(self._ago(hours=3))
        assert result == "3 hours ago"

    def test_singular_hour(self) -> None:
        result = human_delta(self._ago(hours=1, minutes=10))
        assert result == "1 hour ago"

    def test_days_ago(self) -> None:
        result = human_delta(self._ago(days=2))
        assert result == "2 days ago"

    def test_singular_day(self) -> None:
        result = human_delta(self._ago(days=1, hours=2))
        assert result == "1 day ago"

    def test_future_uses_in_prefix(self) -> None:
        result = human_delta(self._ahead(minutes=10))
        assert result.startswith("in ")
        assert "minute" in result

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=2)
        result = human_delta(naive)
        assert "minute" in result
        assert result.endswith("ago")
