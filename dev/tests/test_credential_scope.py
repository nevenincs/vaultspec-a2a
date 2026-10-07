"""The provider credentials a dev scope grants are the names the service knows.

``dev.credentials`` is stdlib-only, so its provider list is spelled out rather
than generated from the service's credential registry. These tests hold the
two together instead, in both directions: the scope grants no name the service
does not declare, and it grants every lane credential the service accepts
under its owning tool's spelling.
"""

from __future__ import annotations

from dev.credentials import _PROVIDER_CREDENTIALS, SCOPES
from vaultspec_a2a.control.env_prefix import ENV_PREFIX
from vaultspec_a2a.control.env_registry import (
    CREDENTIAL_ENV_NAMES,
    FOREIGN_PROVIDER_ENV_NAMES,
)


def test_every_provider_name_a_scope_grants_is_declared_by_the_service() -> None:
    known = CREDENTIAL_ENV_NAMES | FOREIGN_PROVIDER_ENV_NAMES
    stray = sorted(set(_PROVIDER_CREDENTIALS) - known)
    assert not stray, (
        f"dev scope grants provider names the service never names: {stray}"
    )


def test_every_lane_credential_the_service_accepts_is_granted() -> None:
    accepted = {
        name for name in CREDENTIAL_ENV_NAMES if not name.startswith(ENV_PREFIX)
    }
    missing = sorted(accepted - set(_PROVIDER_CREDENTIALS))
    assert not missing, f"lane credentials no dev scope grants: {missing}"


def test_no_scope_grants_the_anthropic_api_key() -> None:
    """The service strips it from every provider child, so no scope injects it."""
    granting = sorted(
        name for name, scope in SCOPES.items() if "ANTHROPIC_API_KEY" in scope.names
    )
    assert not granting, f"scopes granting ANTHROPIC_API_KEY: {granting}"
