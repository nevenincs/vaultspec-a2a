"""The configuration probe reports exactly what the factory would admit.

Under PV06's per-run isolation the factory always launches Kimi inside a
fresh, empty config home, so only the temporary model definition
(``KIMI_MODEL_NAME`` / ``_API_KEY`` / ``_BASE_URL``) can authenticate a served
run - ``settings.kimi_code_home`` is read for prompt-free catalog discovery
against the OPERATOR's own home, never for a served turn. The readiness probe
and the factory's own construction-time refusal must therefore agree for the
identical environment: an operator who set only ``kimi_code_home`` (common
when they also use Kimi's persisted CLI login for discovery) must not be told
the lane is configured when the factory would actually refuse to build it.

Real settings through the production settings overlay; no patching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from ...graph.enums import Provider
from ...testing import settings_override
from .._factory_commands import KIMI_API_KEY_ENV, _build_kimi_env
from ..provider_catalog import HealthState
from ..provider_readiness import (
    KIMI_NO_TEMPORARY_MODEL_REASON,
    probe_provider_configuration,
)

if TYPE_CHECKING:
    from pathlib import Path

_KEY = "sk-kimi-probe-secret"
_BASE_URL = "https://api.moonshot.example/v1"
_MODEL_NAME = "kimi-probe-model"


def _factory_would_admit_credential() -> bool:
    """Whether the factory's own helper would hand the child a Kimi API key.

    ``_build_kimi_env`` is the exact helper ``factory._create_kimi_model``
    calls to decide the identical question
    (``KIMI_API_KEY_ENV not in env_vars``), read straight off the same
    settings the probe reads - the "other side" this module's tests check the
    probe against. A partial definition makes the helper itself raise
    (construction refuses before any env is even assembled), which is just as
    much a refusal to admit a credential as an empty mapping.
    """
    from ...control.config import settings

    key = settings.kimi_api_key.get_secret_value() if settings.kimi_api_key else None
    try:
        env_vars = _build_kimi_env(
            kimi_api_key=key,
            kimi_base_url=settings.kimi_base_url,
            kimi_temporary_model_name=settings.kimi_temporary_model_name,
            kimi_temporary_model_max_context_size=(
                settings.kimi_temporary_model_max_context_size
            ),
            kimi_temporary_model_capabilities=(
                settings.kimi_temporary_model_capabilities
            ),
        )
    except ValueError:
        return False
    return KIMI_API_KEY_ENV in env_vars


def test_an_operators_kimi_code_home_alone_is_not_configured(tmp_path: Path) -> None:
    """The defect this probe once had: ``kimi_code_home`` alone read as ready.

    An operator who only points ``kimi_code_home`` at their own persisted Kimi
    login (for discovery) has configured nothing a served run can authenticate
    from - the factory refuses construction in exactly this environment, so
    the probe must refuse too, with the factory's own reason.
    """
    operator_home = tmp_path / "operator-kimi-home"
    operator_home.mkdir()
    with settings_override(
        kimi_code_home=str(operator_home),
        kimi_model_api_key=None,
        kimi_model_base_url=None,
        kimi_temporary_model_name=None,
    ):
        configuration = probe_provider_configuration(Provider.KIMI)
        factory_admits = _factory_would_admit_credential()

    assert factory_admits is False
    assert configuration.state is HealthState.UNAVAILABLE
    assert configuration.reason == KIMI_NO_TEMPORARY_MODEL_REASON


def test_a_complete_temporary_model_definition_is_configured(tmp_path: Path) -> None:
    """The agreeing case: a complete temporary definition, home set or not."""
    operator_home = tmp_path / "operator-kimi-home"
    operator_home.mkdir()
    with settings_override(
        kimi_code_home=str(operator_home),
        kimi_model_api_key=SecretStr(_KEY),
        kimi_model_base_url=_BASE_URL,
        kimi_temporary_model_name=_MODEL_NAME,
    ):
        configuration = probe_provider_configuration(Provider.KIMI)
        factory_admits = _factory_would_admit_credential()

    assert factory_admits is True
    assert configuration.state is HealthState.AVAILABLE
    assert configuration.reason is None
    assert _KEY not in repr(configuration)


def test_no_configuration_at_all_refuses_with_the_factorys_own_reason() -> None:
    """Nothing set anywhere: refused, not merely unknown - the factory refuses too."""
    with settings_override(
        kimi_code_home=None,
        kimi_model_api_key=None,
        kimi_model_base_url=None,
        kimi_temporary_model_name=None,
    ):
        configuration = probe_provider_configuration(Provider.KIMI)
        factory_admits = _factory_would_admit_credential()

    assert factory_admits is False
    assert configuration.state is HealthState.UNAVAILABLE
    assert configuration.reason == KIMI_NO_TEMPORARY_MODEL_REASON


def test_a_partial_temporary_definition_is_refused_as_malformed() -> None:
    """A partial tuple is refused as incomplete, never silently read as ready."""
    with settings_override(
        kimi_code_home=None,
        kimi_model_api_key=SecretStr(_KEY),
        kimi_model_base_url=None,
        kimi_temporary_model_name=None,
    ):
        configuration = probe_provider_configuration(Provider.KIMI)
        factory_admits = _factory_would_admit_credential()

    assert factory_admits is False
    assert configuration.state is HealthState.UNAVAILABLE
    assert configuration.reason is not None
    assert "incomplete Kimi temporary model definition" in configuration.reason
    assert _KEY not in repr(configuration)
