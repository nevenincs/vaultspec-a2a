"""Tests for enums and constants.

Exercises membership, value types, MODEL_MAP completeness, and
PROVIDER_DEFAULT_MODELS consistency.
"""

from ...graph.enums import (
    MODEL_MAP,
    PROVIDER_DEFAULT_MODELS,
    AgentState,
    Model,
    Provider,
)
from ..enums import (
    AcpRequestId,
    Environment,
    LogLevel,
)

# ---------------------------------------------------------------------------
# StrEnum checks
# ---------------------------------------------------------------------------


class TestAgentState:
    """Tests for the AgentState lifecycle enum."""

    def test_members(self) -> None:
        """All five lifecycle states are present."""
        assert set(AgentState) == {
            AgentState.INIT,
            AgentState.READY,
            AgentState.RUNNING,
            AgentState.ERROR,
            AgentState.DONE,
        }

    def test_values_match_lowercase_names(self) -> None:
        """Each member value is its lowercased name."""
        for member in AgentState:
            assert member.value == member.name.lower()


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
        expected = {"claude", "codex", "gemini", "mock", "openai", "zai", "zhipu"}
        assert {m.value for m in Provider} == expected

    def test_string_comparison(self) -> None:
        """StrEnum values compare equal to plain strings."""
        assert Provider.CLAUDE == "claude"
        assert Provider.GEMINI == "gemini"


class TestModel:
    """Tests for the Model capability level enum."""

    def test_members(self) -> None:
        """All four capability levels are present."""
        expected = {"low", "mid", "high", "max"}
        assert {m.value for m in Model} == expected

    def test_string_comparison(self) -> None:
        """StrEnum values compare equal to plain strings."""
        assert Model.LOW == "low"
        assert Model.MAX == "max"


# ---------------------------------------------------------------------------
# MODEL_MAP completeness
# ---------------------------------------------------------------------------


class TestModelMap:
    """Tests for the MODEL_MAP dict."""

    def test_every_provider_has_entry(self) -> None:
        """MODEL_MAP has a key for every Provider member."""
        for provider in Provider:
            assert provider in MODEL_MAP, f"Missing MODEL_MAP entry for {provider}"

    def test_every_capability_mapped_per_provider(self) -> None:
        """Each provider maps all four capability levels to a non-empty string."""
        for provider in Provider:
            for cap in Model:
                model_name = MODEL_MAP[provider][cap]
                assert isinstance(model_name, str), (
                    f"MODEL_MAP[{provider}][{cap}] is not a str"
                )
                assert len(model_name) > 0, f"MODEL_MAP[{provider}][{cap}] is empty"

    def test_no_extra_providers(self) -> None:
        """MODEL_MAP does not contain keys outside the Provider enum."""
        for key in MODEL_MAP:
            assert key in Provider, f"Unexpected MODEL_MAP key: {key}"


# ---------------------------------------------------------------------------
# PROVIDER_DEFAULT_MODELS consistency
# ---------------------------------------------------------------------------


class TestProviderDefaultModels:
    """Tests for the PROVIDER_DEFAULT_MODELS dict."""

    def test_every_provider_has_default(self) -> None:
        """Every Provider has a default model capability."""
        for provider in Provider:
            assert provider in PROVIDER_DEFAULT_MODELS, (
                f"Missing default model for {provider}"
            )

    def test_defaults_are_valid_capabilities(self) -> None:
        """Each default is a valid Model enum member."""
        for provider, cap in PROVIDER_DEFAULT_MODELS.items():
            assert cap in Model, f"Invalid capability {cap} for {provider}"

    def test_defaults_resolve_in_model_map(self) -> None:
        """Each default capability maps to a concrete model name in MODEL_MAP."""
        for provider, cap in PROVIDER_DEFAULT_MODELS.items():
            model_name = MODEL_MAP[provider][cap]
            assert len(model_name) > 0


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
            "SESSION_SET_MODEL",
            "SESSION_SET_CONFIG_OPTION",
            "SESSION_CANCEL",
        }
        actual_names = {m.name for m in AcpRequestId}
        assert actual_names == expected_names
