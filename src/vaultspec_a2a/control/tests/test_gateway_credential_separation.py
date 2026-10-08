"""Gateway and worker credentials are distinct authority domains."""

import pytest
from pydantic import ValidationError

from ...control.config import Settings
from ...desktop.credentials import MAX_CREDENTIAL_BYTES


def test_settings_reject_reused_gateway_and_worker_credentials() -> None:
    """An operator cannot configure one bearer for both trust boundaries."""
    with pytest.raises(
        ValidationError,
        match=(
            "VAULTSPEC_A2A_GATEWAY_TOKEN must differ from VAULTSPEC_A2A_INTERNAL_TOKEN"
        ),
    ):
        Settings(
            internal_token="one-shared-secret",
            VAULTSPEC_A2A_GATEWAY_TOKEN="one-shared-secret",
        )


def test_settings_accept_distinct_gateway_and_worker_credentials() -> None:
    """Independent configured credentials remain supported."""
    settings = Settings(
        internal_token="worker-secret",
        VAULTSPEC_A2A_GATEWAY_TOKEN="gateway-secret",
    )

    assert settings.internal_token == "worker-secret"
    assert settings.gateway_service_token == "gateway-secret"


def test_a_gateway_token_too_long_to_publish_is_refused_at_configuration() -> None:
    """An over-long gateway bearer fails here, not later at discovery.

    The configured gateway bearer is published verbatim into the owner-restricted
    handoff credential beside the discovery record, and every reader loads that
    file through a bound of ``MAX_CREDENTIAL_BYTES``. A longer token therefore
    publishes a credential nothing can read, and the operator learns about it as
    an attach failure against a gateway that started cleanly. The bound belongs
    where the value is configured.

    The length is measured in BYTES, as the credential file's bound is, so the
    boundary case is one byte over on a multi-byte character rather than one
    character over.
    """
    with pytest.raises(ValidationError, match="VAULTSPEC_A2A_GATEWAY_TOKEN"):
        Settings(VAULTSPEC_A2A_GATEWAY_TOKEN="a" * (MAX_CREDENTIAL_BYTES + 1))


def test_a_gateway_token_at_the_publishable_bound_is_accepted() -> None:
    """The bound is inclusive, so a token the credential file can hold is valid."""
    at_bound = "a" * MAX_CREDENTIAL_BYTES

    settings = Settings(VAULTSPEC_A2A_GATEWAY_TOKEN=at_bound)

    assert settings.gateway_service_token == at_bound


def test_the_gateway_token_bound_counts_bytes_not_characters() -> None:
    """A token inside the character count but over the byte bound is refused.

    Multi-byte characters are what make the two readings differ, and the file
    bound the publication must satisfy is a byte bound.
    """
    multibyte = "é" * (MAX_CREDENTIAL_BYTES // 2 + 1)
    assert len(multibyte) <= MAX_CREDENTIAL_BYTES
    assert len(multibyte.encode("utf-8")) > MAX_CREDENTIAL_BYTES

    with pytest.raises(ValidationError, match="VAULTSPEC_A2A_GATEWAY_TOKEN"):
        Settings(VAULTSPEC_A2A_GATEWAY_TOKEN=multibyte)
