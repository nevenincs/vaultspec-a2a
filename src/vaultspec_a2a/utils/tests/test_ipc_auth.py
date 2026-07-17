"""The shared internal-IPC bearer verifier (gateway <-> worker single home)."""

from __future__ import annotations

from vaultspec_a2a.utils.enums import Environment
from vaultspec_a2a.utils.ipc_auth import BearerVerdict, verify_internal_bearer


def test_dev_mode_unset_token_disables_auth() -> None:
    verdict, detail = verify_internal_bearer(
        None, token=None, environment=Environment.DEVELOPMENT
    )
    assert verdict is BearerVerdict.OK
    assert detail == ""


def test_unset_token_outside_dev_is_misconfigured() -> None:
    verdict, detail = verify_internal_bearer(
        "Bearer anything", token=None, environment=Environment.PRODUCTION
    )
    assert verdict is BearerVerdict.MISCONFIGURED
    assert "VAULTSPEC_INTERNAL_TOKEN required" in detail
    assert "production" in detail


def test_matching_bearer_is_ok() -> None:
    verdict, detail = verify_internal_bearer(
        "Bearer s3cr3t", token="s3cr3t", environment=Environment.PRODUCTION
    )
    assert verdict is BearerVerdict.OK
    assert detail == ""


def test_mismatched_bearer_is_unauthorized() -> None:
    verdict, detail = verify_internal_bearer(
        "Bearer wrong", token="s3cr3t", environment=Environment.TESTING
    )
    assert verdict is BearerVerdict.UNAUTHORIZED
    assert detail == "Invalid internal token"


def test_missing_header_is_unauthorized() -> None:
    verdict, _ = verify_internal_bearer(
        None, token="s3cr3t", environment=Environment.PRODUCTION
    )
    assert verdict is BearerVerdict.UNAUTHORIZED
