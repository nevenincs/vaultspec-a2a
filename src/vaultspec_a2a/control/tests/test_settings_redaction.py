"""What a refusal is allowed to quote back, and what it must not.

A refusal names the variable and the value, because that is what fixes the
mistake in one pass. Two kinds of value are exempt: a credential, which the
message names without quoting, and the userinfo of any URL, which is where a
database DSN carries its password on a field no name test calls a secret.
"""

import pickle
from pathlib import Path

import pytest
from vaultspec_core.config import ConfigurationError

from ...domain_config import DomainSettingsConfig
from ...testing import armed_environment
from ..config import Settings, settings
from ..settings_base import ENV_FILE_ENV, PROJECT_ROOT_ENV, read_configuration


def test_a_rejected_database_url_never_carries_its_password(tmp_path: Path) -> None:
    """A DSN is a plain string on a field no name test calls a secret."""
    with (
        armed_environment(**{PROJECT_ROOT_ENV: str(tmp_path), ENV_FILE_ENV: None}),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(
            Settings, database_url=["postgresql+asyncpg://dbuser:hunter2@dbhost/app"]
        )

    reported = str(refusal.value)
    assert "hunter2" not in reported
    assert "dbuser" not in reported
    # The scheme and the host survive, which is what names the store.
    assert "postgresql+asyncpg://<redacted>@dbhost/app" in reported


def test_a_rejected_backend_never_carries_the_urls_password(tmp_path: Path) -> None:
    """The same holds for a whole-model refusal, which renders its own message."""
    with (
        armed_environment(
            **{
                PROJECT_ROOT_ENV: str(tmp_path),
                ENV_FILE_ENV: None,
                "VAULTSPEC_A2A_DATABASE_URL": (
                    "mysql+aiomysql://dbuser:hunter2@dbhost:3306/app"
                ),
            }
        ),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(Settings)

    reported = str(refusal.value)
    assert "hunter2" not in reported
    assert "VAULTSPEC_A2A_DATABASE_URL" in reported


def test_a_rejected_api_key_is_named_by_its_variable_alone(tmp_path: Path) -> None:
    """A SecretStr-typed credential is redacted by its type, not by a list."""
    with (
        armed_environment(**{PROJECT_ROOT_ENV: str(tmp_path), ENV_FILE_ENV: None}),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(Settings, kimi_model_api_key=["sk-live-secret"])

    reported = str(refusal.value)
    assert "sk-live-secret" not in reported
    assert "VAULTSPEC_A2A_KIMI_MODEL_API_KEY must be" in reported


def test_a_size_named_tokens_still_shows_the_value_it_refused(tmp_path: Path) -> None:
    """The secret vocabulary reads the type too: a count of tokens is not a token."""
    with (
        armed_environment(
            **{
                PROJECT_ROOT_ENV: str(tmp_path),
                ENV_FILE_ENV: None,
                "VAULTSPEC_A2A_CONTEXT_LIMIT_TOKENS": "loads",
            }
        ),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(DomainSettingsConfig)

    assert "VAULTSPEC_A2A_CONTEXT_LIMIT_TOKENS must be int, got 'loads'" in str(
        refusal.value
    )


def test_the_settings_singleton_refuses_to_be_pickled() -> None:
    """A pickled stand-in would rebuild from the receiver's own environment."""
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(settings)


def test_the_settings_singleton_compares_by_its_values() -> None:
    """Comparison reaches the settings, not the stand-in's identity."""
    assert settings == Settings()
    assert settings != "not the settings"
    assert bool(settings)
