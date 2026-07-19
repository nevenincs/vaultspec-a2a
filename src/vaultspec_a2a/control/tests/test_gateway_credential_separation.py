"""Gateway and worker credentials are distinct authority domains."""

import pytest
from pydantic import ValidationError

from vaultspec_a2a.control.config import Settings


def test_settings_reject_reused_gateway_and_worker_credentials() -> None:
    """An operator cannot configure one bearer for both trust boundaries."""
    with pytest.raises(
        ValidationError,
        match="VAULTSPEC_A2A_GATEWAY_TOKEN must differ from VAULTSPEC_INTERNAL_TOKEN",
    ):
        Settings(
            VAULTSPEC_INTERNAL_TOKEN="one-shared-secret",
            VAULTSPEC_A2A_GATEWAY_TOKEN="one-shared-secret",
        )


def test_settings_accept_distinct_gateway_and_worker_credentials() -> None:
    """Independent configured credentials remain supported."""
    settings = Settings(
        VAULTSPEC_INTERNAL_TOKEN="worker-secret",
        VAULTSPEC_A2A_GATEWAY_TOKEN="gateway-secret",
    )

    assert settings.internal_token == "worker-secret"
    assert settings.gateway_service_token == "gateway-secret"
