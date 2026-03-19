"""Tests for the core configuration settings."""

from pathlib import Path

import pytest

from ...utils import Environment, LogLevel
from ..config import Settings


def test_config_default_values() -> None:
    """Verify that Settings loads default values correctly."""
    settings = Settings()
    assert settings.environment == Environment.DEVELOPMENT
    assert settings.log_level == LogLevel.INFO
    assert settings.workspace_root == Path("./workspaces")


def test_config_vaultspec_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that VAULTSPEC_ prefixed environment variables are prioritized."""
    test_path = str(Path("./test_workspace_override").absolute())
    monkeypatch.setenv("VAULTSPEC_ENVIRONMENT", Environment.PRODUCTION.value)
    monkeypatch.setenv("VAULTSPEC_LOG_LEVEL", LogLevel.ERROR.value)
    monkeypatch.setenv("VAULTSPEC_WORKSPACE_ROOT", test_path)

    # Initialize settings - it should automatically bind VAULTSPEC_ variables
    settings = Settings()
    assert settings.environment == Environment.PRODUCTION
    assert settings.log_level == LogLevel.ERROR
    assert settings.workspace_root == Path(test_path)


def test_config_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that standard ecosystem environment variables are picked up via aliases.

    Tests that standard ecosystem names (without VAULTSPEC_ prefix) are picked
    up via AliasChoices.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-test")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("NO_COLOR", "1")

    settings = Settings()
    assert settings.anthropic_api_key == "sk-anthropic-test"
    assert settings.ci is True
    assert settings.no_color is True

    # Verify bare ecosystem name takes precedence over VAULTSPEC_ prefix
    # (guaranteed by AliasChoices order in src/vaultspec_a2a/core/config.py —
    # bare key first).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-standard-priority")
    monkeypatch.setenv("VAULTSPEC_ANTHROPIC_API_KEY", "sk-vaultspec-ignored")
    monkeypatch.setenv("VAULTSPEC_CI", "false")
    monkeypatch.setenv("CI", "true")

    settings = Settings()
    assert settings.anthropic_api_key == "sk-standard-priority"
    assert settings.ci is False


def test_blank_internal_token_disables_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank internal tokens should normalize to None for dev/test IPC."""
    monkeypatch.setenv("VAULTSPEC_INTERNAL_TOKEN", "")

    settings = Settings()

    assert settings.internal_token is None
