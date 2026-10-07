"""The configuration probe reports the Claude lane's declared channel honestly.

Claude configures itself through a declared auth channel, and the channel
selector at the lane's root seam is the authority on whether that channel has
anything to present. The probe asks it, so a configured Claude lane is reported
configured, an unsatisfiable channel is reported unavailable with its own
sentence, and the ambient case - a CLI running on its own persisted login - stays
unknown instead of being claimed either way.

Real settings through the production settings overlay and a real child
environment; no patching, and the credential never leaves the verdict.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from ...graph.enums import Provider
from ...testing import armed_environment, settings_override
from ..provider_catalog import HealthState
from ..provider_readiness import (
    probe_provider_configuration,
    probe_provider_readiness,
)

_SECRET = "configured-probe-token"


def test_the_oauth_channel_with_its_token_is_configured() -> None:
    with settings_override(
        claude_auth_channel="oauth_token",
        claude_code_oauth_token=SecretStr(_SECRET),
    ):
        configuration = probe_provider_configuration(Provider.CLAUDE)

    assert configuration.state is HealthState.AVAILABLE
    assert configuration.reason is None
    assert _SECRET not in repr(configuration)


@pytest.mark.parametrize("token", (None, SecretStr("   ")))
def test_the_oauth_channel_without_a_token_is_unavailable_with_its_own_reason(
    token: SecretStr | None,
) -> None:
    """The channel selector's refusal is the probe's reason, not a restatement."""
    with settings_override(
        claude_auth_channel="oauth_token",
        claude_code_oauth_token=token,
    ):
        configuration = probe_provider_configuration(Provider.CLAUDE)
        readiness = probe_provider_readiness(Provider.CLAUDE)

    assert configuration.state is HealthState.UNAVAILABLE
    assert configuration.reason == (
        "Claude oauth_token auth channel requires a configured OAuth token"
    )
    # The configured state joins readiness: the lane is refused here rather than
    # travelling on to a command check that would have called it ready.
    assert readiness.ready is False
    assert readiness.reason == configuration.reason


def test_the_subscription_channels_operator_export_is_configured() -> None:
    with (
        settings_override(
            claude_auth_channel="subscription_login",
            claude_code_oauth_token=None,
        ),
        armed_environment(CLAUDE_CODE_OAUTH_TOKEN=_SECRET),
    ):
        configuration = probe_provider_configuration(Provider.CLAUDE)

    assert configuration.state is HealthState.AVAILABLE
    assert configuration.reason is None
    assert _SECRET not in repr(configuration)


def test_the_subscription_channel_without_an_export_stays_unknown() -> None:
    """A persisted CLI login is state this probe cannot read, so it claims neither."""
    with (
        settings_override(
            claude_auth_channel="subscription_login",
            claude_code_oauth_token=SecretStr(_SECRET),
        ),
        armed_environment(CLAUDE_CODE_OAUTH_TOKEN=None),
    ):
        configuration = probe_provider_configuration(Provider.CLAUDE)

    assert configuration.state is HealthState.UNKNOWN
    assert configuration.reason is None


def test_a_blank_operator_export_is_not_a_configured_credential() -> None:
    with (
        settings_override(
            claude_auth_channel="subscription_login",
            claude_code_oauth_token=None,
        ),
        armed_environment(CLAUDE_CODE_OAUTH_TOKEN="   "),
    ):
        configuration = probe_provider_configuration(Provider.CLAUDE)

    assert configuration.state is HealthState.UNKNOWN
