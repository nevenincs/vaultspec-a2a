"""Resolution rules for the shared gateway attach bearer.

Real Settings state and a real owner-restricted credential file exercise each
resolution tier; no mocks, patches, or fake transports.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.gateway_auth import resolve_gateway_bearer
from vaultspec_a2a.desktop._platform_acl import harden_credential_file
from vaultspec_a2a.desktop.credentials import ATTACH_CREDENTIAL_NAME
from vaultspec_a2a.desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_CONFIGURED = "configured-service-token-1234567890abcdef"
_ATTACH = "attach-credential-token-a0b1c2d3e4f5a6b7"
_LOOPBACK = "http://127.0.0.1:18000"
_REMOTE = "http://gateway.example.com:18000"


@contextmanager
def _override(**updates: object) -> Iterator[None]:
    originals = {name: getattr(settings, name) for name in updates}
    for name, value in updates.items():
        setattr(settings, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(settings, name, value)


def _seed_attach_file(app_home: Path) -> None:
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    attach = state.credentials_dir / ATTACH_CREDENTIAL_NAME
    attach.write_text(_ATTACH, encoding="utf-8")
    harden_credential_file(attach)


def test_configured_token_is_authoritative_for_any_host() -> None:
    """A configured service token wins over host and profile state."""
    with _override(gateway_service_token=_CONFIGURED, desktop_app_home=None):
        assert resolve_gateway_bearer(_LOOPBACK) == _CONFIGURED
        assert resolve_gateway_bearer(_REMOTE) == _CONFIGURED


def test_remote_url_receives_no_machine_local_credential(tmp_path: Path) -> None:
    """A non-loopback target never gets the desktop attach credential."""
    home = tmp_path / "app-home"
    home.mkdir()
    _seed_attach_file(home)
    with _override(gateway_service_token=None, desktop_app_home=home):
        assert resolve_gateway_bearer(_REMOTE) is None


def test_armed_desktop_attach_credential_on_loopback(tmp_path: Path) -> None:
    """An armed loopback caller resolves the owner-scoped attach credential."""
    home = tmp_path / "app-home"
    home.mkdir()
    _seed_attach_file(home)
    with _override(gateway_service_token=None, desktop_app_home=home):
        assert resolve_gateway_bearer(_LOOPBACK) == _ATTACH


def test_unarmed_loopback_without_discovery_resolves_nothing() -> None:
    """An unarmed loopback caller with no configured token resolves no bearer."""
    with _override(gateway_service_token=None, desktop_app_home=None):
        # Port 1 never hosts a fresh resident matching this request.
        assert resolve_gateway_bearer("http://127.0.0.1:1") is None
