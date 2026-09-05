"""Provider catalog settings must resolve one execution lane deterministically."""

from pathlib import Path
from typing import Protocol, cast

import pytest
from pydantic import ValidationError

from ..config import Settings


class _SettingsEnvFileFactory(Protocol):
    def __call__(self, *, _env_file: Path) -> Settings: ...


def test_kimi_temporary_provider_uses_only_current_names() -> None:
    configured = Settings.model_validate(
        {
            "KIMI_MODEL_API_KEY": "current-key",
            "KIMI_MODEL_BASE_URL": "https://current.example.invalid/v1",
            "KIMI_MODEL_NAME": "configured-alias",
            "KIMI_MODEL_MAX_CONTEXT_SIZE": "131072",
            "KIMI_MODEL_CAPABILITIES": " thinking, image_in,thinking ",
            "KIMI_CODE_HOME": "C:/isolated-kimi-home",
        }
    )

    assert configured.kimi_api_key is not None
    assert configured.kimi_api_key.get_secret_value() == "current-key"
    assert configured.kimi_base_url == "https://current.example.invalid/v1"
    assert configured.kimi_temporary_model_name == "configured-alias"
    assert configured.kimi_temporary_model_max_context_size == 131072
    assert configured.kimi_temporary_model_capabilities == "thinking,image_in"
    assert configured.kimi_code_home == "C:/isolated-kimi-home"


def test_retired_kimi_key_and_base_names_are_ignored() -> None:
    configured = Settings.model_validate(
        {
            "KIMI_API_KEY": "obsolete-key",
            "KIMI_BASE_URL": "https://obsolete.example.invalid/v1",
        }
    )

    assert configured.kimi_api_key is None
    assert configured.kimi_base_url is None


def test_retired_kimi_names_cannot_override_current_names() -> None:
    configured = Settings.model_validate(
        {
            "KIMI_MODEL_API_KEY": "current-key",
            "KIMI_API_KEY": "obsolete-key",
            "KIMI_MODEL_BASE_URL": "https://current.example.invalid/v1",
            "KIMI_BASE_URL": "https://obsolete.example.invalid/v1",
        }
    )

    assert configured.kimi_api_key is not None
    assert configured.kimi_api_key.get_secret_value() == "current-key"
    assert configured.kimi_base_url == "https://current.example.invalid/v1"


@pytest.mark.parametrize("current", ("", "   "))
def test_blank_current_kimi_names_do_not_fall_through_to_retired_names(
    current: str,
) -> None:
    configured = Settings.model_validate(
        {
            "KIMI_MODEL_API_KEY": current,
            "KIMI_API_KEY": "legacy-key",
            "KIMI_MODEL_BASE_URL": current,
            "KIMI_BASE_URL": "https://legacy.example.invalid/v1",
        }
    )

    assert configured.kimi_api_key is None
    assert configured.kimi_base_url is None


def test_retired_kimi_names_in_a_real_env_file_are_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KIMI_MODEL_API_KEY=\n"
        "KIMI_API_KEY=legacy-file-key\n"
        "KIMI_MODEL_BASE_URL=   \n"
        "KIMI_BASE_URL=https://legacy-file.example.invalid/v1\n",
        encoding="utf-8",
    )

    configured = cast("_SettingsEnvFileFactory", Settings)(_env_file=env_file)

    assert configured.kimi_api_key is None
    assert configured.kimi_base_url is None


def test_absent_kimi_current_values_remain_absent() -> None:
    configured = Settings.model_validate({})

    assert configured.kimi_api_key is None
    assert configured.kimi_base_url is None


def test_kimi_secret_inputs_are_excluded_from_repr_and_model_dump() -> None:
    current_secret = "current-key-that-must-not-leak"
    retired_secret = "retired-key-that-must-not-leak"
    configured = Settings.model_validate(
        {
            "KIMI_MODEL_API_KEY": current_secret,
            "KIMI_API_KEY": retired_secret,
        }
    )

    rendered = f"{configured!r}\n{configured.model_dump()!r}"
    assert current_secret not in rendered
    assert retired_secret not in rendered
    assert "kimi_model_api_key" not in configured.model_dump()
    assert "kimi_legacy_api_key" not in Settings.model_fields


@pytest.mark.parametrize(
    "value",
    ("0", "-1", "2147483648", "not-an-integer"),
)
def test_invalid_kimi_context_size_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"KIMI_MODEL_MAX_CONTEXT_SIZE": value})


@pytest.mark.parametrize(
    "value",
    ("thinking,,image_in", f"x{'y' * 64}", "thinking,not a token"),
)
def test_invalid_kimi_capabilities_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"KIMI_MODEL_CAPABILITIES": value})


def test_openai_base_url_is_one_explicit_execution_and_catalog_setting() -> None:
    configured = Settings.model_validate(
        {"OPENAI_BASE_URL": "https://openai-compatible.example.invalid/v1"}
    )

    assert configured.openai_base_url == "https://openai-compatible.example.invalid/v1"
