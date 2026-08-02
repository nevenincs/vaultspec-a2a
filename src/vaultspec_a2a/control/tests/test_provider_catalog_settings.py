"""Provider catalog settings must resolve one execution lane deterministically."""

from ..config import Settings


def test_kimi_temporary_provider_uses_only_current_names() -> None:
    configured = Settings.model_validate(
        {
            "KIMI_MODEL_API_KEY": "current-key",
            "KIMI_MODEL_BASE_URL": "https://current.example.invalid/v1",
            "KIMI_MODEL_NAME": "configured-alias",
            "KIMI_CODE_HOME": "C:/isolated-kimi-home",
        }
    )

    assert configured.kimi_api_key is not None
    assert configured.kimi_api_key.get_secret_value() == "current-key"
    assert configured.kimi_base_url == "https://current.example.invalid/v1"
    assert configured.kimi_temporary_model_name == "configured-alias"
    assert configured.kimi_code_home == "C:/isolated-kimi-home"


def test_legacy_kimi_key_and_base_names_do_not_configure_a_provider() -> None:
    configured = Settings.model_validate(
        {
            "KIMI_API_KEY": "obsolete-key",
            "KIMI_BASE_URL": "https://obsolete.example.invalid/v1",
        }
    )

    assert configured.kimi_api_key is None
    assert configured.kimi_base_url is None


def test_openai_base_url_is_one_explicit_execution_and_catalog_setting() -> None:
    configured = Settings.model_validate(
        {"OPENAI_BASE_URL": "https://openai-compatible.example.invalid/v1"}
    )

    assert configured.openai_base_url == "https://openai-compatible.example.invalid/v1"
