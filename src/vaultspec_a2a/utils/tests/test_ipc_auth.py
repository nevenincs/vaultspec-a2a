"""The shared internal-IPC bearer verifier (gateway <-> worker single home)."""

from __future__ import annotations

from ...utils.enums import Environment
from ...utils.ipc_auth import BearerVerdict, verify_internal_bearer


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


def test_wrong_tokens_of_every_length_are_rejected() -> None:
    """A wrong bearer is rejected whether it is shorter, equal, or longer.

    The constant-time compare handles unequal-length inputs without leaking, so
    each of these must reject identically rather than one path short-circuiting.
    """
    for supplied in ("Bearer", "Bearer wrong0", "Bearer s3cr3tX", "Bearer " + "x" * 64):
        verdict, detail = verify_internal_bearer(
            supplied, token="s3cr3t", environment=Environment.TESTING
        )
        assert verdict is BearerVerdict.UNAUTHORIZED
        assert detail == "Invalid internal token"


def test_comparison_path_uses_the_constant_time_helper() -> None:
    """The secret comparison routes through ``hmac.compare_digest``.

    Certified at the source level so a future refactor cannot silently reintroduce
    a data-dependent ``==``/``!=`` compare of the worker-IPC secret.
    """
    import inspect

    source = inspect.getsource(verify_internal_bearer)
    assert "hmac.compare_digest" in source
    assert 'f"Bearer {token}"' in source


class TestOmissionIsNotConsent:
    """A defaulted environment must not disable authentication.

    The bypass exists so a developer can run without minting a token. It was
    keyed on the environment's VALUE, which has a default, so a deployment that
    configured neither an environment nor a token served the internal surface
    unauthenticated - and the loud refusal meant to prevent that could only fire
    for an operator who had already set the variable the refusal asks about.
    """

    def test_a_declared_development_environment_still_disables_auth(self) -> None:
        verdict, _ = verify_internal_bearer(
            None,
            token=None,
            environment=Environment.DEVELOPMENT,
            environment_declared=True,
        )
        assert verdict is BearerVerdict.OK

    def test_an_undeclared_environment_refuses_instead_of_bypassing(self) -> None:
        verdict, detail = verify_internal_bearer(
            None,
            token=None,
            environment=Environment.DEVELOPMENT,
            environment_declared=False,
        )
        assert verdict is BearerVerdict.MISCONFIGURED
        # The refusal names the two ways out rather than only the failure.
        assert "no environment was declared" in detail
        assert "VAULTSPEC_ENVIRONMENT=development" in detail

    def test_a_token_authorizes_regardless_of_declaration(self) -> None:
        """The bypass is the only thing the distinction gates."""
        verdict, _ = verify_internal_bearer(
            "Bearer secret",
            token="secret",
            environment=Environment.DEVELOPMENT,
            environment_declared=False,
        )
        assert verdict is BearerVerdict.OK

    def test_a_declared_non_development_environment_is_unchanged(self) -> None:
        verdict, detail = verify_internal_bearer(
            None,
            token=None,
            environment=Environment.PRODUCTION,
            environment_declared=True,
        )
        assert verdict is BearerVerdict.MISCONFIGURED
        assert "production" in detail
