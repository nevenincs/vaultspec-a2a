from pathlib import Path

import pytest

from ...utils import Environment, LogLevel
from ..config import Settings


def test_config_default_values() -> None:
    settings = Settings()
    assert settings.environment == Environment.DEVELOPMENT
    assert settings.log_level == LogLevel.INFO
    assert settings.workspace_root == Path("./workspaces")


def test_config_vaultspec_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
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
    # Test that standard ecosystem names (without VAULTSPEC_ prefix) are picked up via AliasChoices
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-test")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("NO_COLOR", "1")

    settings = Settings()
    assert settings.anthropic_api_key == "sk-anthropic-test"
    assert settings.ci is True
    assert settings.no_color is True

    # Verify that VAULTSPEC_ prefix correctly takes precedence over standard ecosystem names.
    # This behavior is guaranteed by the order in AliasChoices in lib/core/config.py.
    monkeypatch.setenv("VAULTSPEC_ANTHROPIC_API_KEY", "sk-vaultspec-priority")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-standard-ignored")
    monkeypatch.setenv("VAULTSPEC_CI", "false")
    monkeypatch.setenv("CI", "true")

    settings = Settings()
    assert settings.anthropic_api_key == "sk-vaultspec-priority"
    assert settings.ci is False
