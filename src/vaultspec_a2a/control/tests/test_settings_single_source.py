"""Every setting has one owner, and the committed port table agrees with it.

The service reads two settings singletons from one environment: ``settings`` for
infrastructure and ``domain_config`` for behavioural knobs. A field declared by
both would answer two different values after one in-process override, so the
field sets and the environment names they read must stay disjoint, and a test
override must land on the singleton that declares the name it sets.

``procs.toml`` repeats the resident gateway and worker ports so the dev process
registry can keep clear of them. The settings defaults own those two numbers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain_config import DomainSettingsConfig, domain_config
from ...lifecycle import load_procs_config
from ...testing import settings_override
from ..config import Settings, settings
from ..settings_base import field_env_names
from ._env_example import REPO_ROOT

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings

# The resident services whose port a settings field also declares. The engine is
# a separate product that announces its own port, so no a2a setting backs it.
_RESIDENT_PORT_FIELDS = {"gateway": "port", "worker": "worker_port"}


def _environment_names(settings_cls: type[BaseSettings]) -> set[str]:
    return {
        name
        for field in settings_cls.model_fields
        for name in field_env_names(settings_cls, field)
    }


def test_no_field_is_declared_by_both_singletons() -> None:
    domain_fields = set(DomainSettingsConfig.model_fields)
    infra_fields = set(Settings.model_fields)

    assert domain_fields
    assert infra_fields
    assert not domain_fields & infra_fields, sorted(domain_fields & infra_fields)


def test_no_environment_name_is_read_by_both_singletons() -> None:
    domain_names = _environment_names(DomainSettingsConfig)
    infra_names = _environment_names(Settings)

    assert not domain_names & infra_names, sorted(domain_names & infra_names)


def test_an_override_lands_on_the_singleton_that_declares_the_field() -> None:
    domain_original = domain_config.max_stream_connections
    infra_original = settings.stream_heartbeat_interval_seconds

    with settings_override(
        max_stream_connections=domain_original + 1,
        stream_heartbeat_interval_seconds=infra_original + 1.0,
    ):
        assert domain_config.max_stream_connections == domain_original + 1
        assert settings.stream_heartbeat_interval_seconds == infra_original + 1.0
        assert not hasattr(settings, "max_stream_connections")
        assert not hasattr(domain_config, "stream_heartbeat_interval_seconds")

    assert domain_config.max_stream_connections == domain_original
    assert settings.stream_heartbeat_interval_seconds == infra_original


def test_resident_ports_equal_the_service_defaults() -> None:
    resident = load_procs_config(REPO_ROOT / "procs.toml").resident

    for service, field in _RESIDENT_PORT_FIELDS.items():
        assert service in resident, service
        assert resident[service] == Settings.model_fields[field].default, service
