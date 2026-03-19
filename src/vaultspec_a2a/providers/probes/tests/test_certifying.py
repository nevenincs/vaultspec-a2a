"""Focused tests for the certifying provider-probe selector."""

from __future__ import annotations

from .. import certifying


def test_probe_timeout_seconds_disables_outer_timeout_for_interactive_providers() -> (
    None
):
    """Interactive ACP providers should rely on their internal auth watchdogs."""
    assert certifying._probe_timeout_seconds("claude") is None
    assert certifying._probe_timeout_seconds("gemini") is None


def test_probe_timeout_seconds_preserves_short_watchdogs_for_api_providers() -> None:
    """API-key-backed providers keep the bounded wrapper timeout."""
    assert certifying._probe_timeout_seconds("openai") == 90
    assert certifying._probe_timeout_seconds("zhipu") == 90
