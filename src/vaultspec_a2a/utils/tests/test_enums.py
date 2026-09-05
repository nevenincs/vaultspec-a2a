"""Tests for enums and constants.

Exercises enum membership and value types.
"""

from ...graph.enums import Provider
from ..enums import (
    AcpRequestId,
    Environment,
    LogLevel,
)

# ---------------------------------------------------------------------------
# StrEnum checks
# ---------------------------------------------------------------------------


class TestLogLevel:
    """Tests for the LogLevel enum."""

    def test_members(self) -> None:
        """All five logging levels are present."""
        expected = {"debug", "info", "warning", "error", "critical"}
        assert {m.value for m in LogLevel} == expected


class TestEnvironment:
    """Tests for the Environment enum."""

    def test_members(self) -> None:
        """All four environments are present."""
        expected = {"development", "testing", "staging", "production"}
        assert {m.value for m in Environment} == expected


class TestProvider:
    """Tests for the Provider enum."""

    def test_members(self) -> None:
        """All providers are present."""
        expected = {
            "antigravity",
            "claude",
            "codex",
            "deterministic",
            "kimi",
            "mock",
            "openai",
            "zai",
            "zhipu",
        }
        assert {m.value for m in Provider} == expected

    def test_string_comparison(self) -> None:
        """StrEnum values compare equal to plain strings."""
        assert Provider.CLAUDE == "claude"


# ---------------------------------------------------------------------------
# AcpRequestId
# ---------------------------------------------------------------------------


class TestAcpRequestId:
    """Tests for the AcpRequestId IntEnum."""

    def test_initialize_id(self) -> None:
        """INITIALIZE has the base value 1000."""
        assert AcpRequestId.INITIALIZE == 1000

    def test_all_ids_are_unique(self) -> None:
        """No two members share the same integer value."""
        values = [m.value for m in AcpRequestId]
        assert len(values) == len(set(values))

    def test_ids_are_integers(self) -> None:
        """All members are ints."""
        for member in AcpRequestId:
            assert isinstance(member, int)

    def test_known_members(self) -> None:
        """All expected RPC identifiers exist."""
        expected_names = {
            "INITIALIZE",
            "SESSION_SETUP",
            "SESSION_PROMPT",
            "AUTHENTICATE",
            "SESSION_FORK",
            "SESSION_LIST",
            "SESSION_SET_MODE",
            "SESSION_SET_CONFIG_OPTION",
            "SESSION_CANCEL",
        }
        actual_names = {m.name for m in AcpRequestId}
        assert actual_names == expected_names
