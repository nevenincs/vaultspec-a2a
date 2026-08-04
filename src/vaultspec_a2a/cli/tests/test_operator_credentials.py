"""Operator calls read owner-scoped credential files, never secret arguments."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import click

from ...cli.main import main
from ...desktop._platform_acl import harden_credential_path
from ...desktop.credentials import ATTACH_CREDENTIAL_NAME
from ...desktop.profile import derive_state_paths
from ...gateway_auth import gateway_auth_headers
from ...lifecycle.discovery import (
    service_json_path,
    write_desktop_discovery,
)
from ...testing import settings_override as _settings_override

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_TOKEN = "attach-credential-token-a0b1c2d3e4f5a6b7"


def _seed_desktop_authority(app_home: Path, a2a_home: Path, *, port: int) -> None:
    """Write the credential and matching live desktop discovery authority."""
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    attach = state.credentials_dir / ATTACH_CREDENTIAL_NAME
    attach.write_text(_TOKEN, encoding="utf-8")
    harden_credential_path(attach)
    write_desktop_discovery(
        service_json_path(a2a_home),
        generation="gateway-auth-test-generation",
        port=port,
        owner="gateway-auth-test-owner",
        credential_reference=str(attach),
        pid=os.getpid(),
    )


def test_desktop_credential_requires_matching_live_discovery(tmp_path: Path) -> None:
    """The validated desktop origin receives its attach credential."""
    home = tmp_path / "app-home"
    home.mkdir()
    a2a_home = tmp_path / "a2a-home"
    _seed_desktop_authority(home, a2a_home, port=8123)
    with _settings_override(
        desktop_app_home=home,
        a2a_home=a2a_home,
        gateway_service_token=None,
    ):
        assert gateway_auth_headers("http://127.0.0.1:8123/v1/service") == {
            "Authorization": f"Bearer {_TOKEN}"
        }


def test_desktop_credential_is_not_sent_to_wrong_loopback_port(tmp_path: Path) -> None:
    """A different loopback listener never receives the desktop credential."""
    home = tmp_path / "app-home"
    home.mkdir()
    a2a_home = tmp_path / "a2a-home"
    _seed_desktop_authority(home, a2a_home, port=8123)
    with _settings_override(
        desktop_app_home=home,
        a2a_home=a2a_home,
        gateway_service_token=None,
    ):
        assert gateway_auth_headers("http://127.0.0.1:8124/v1/service") == {}


def test_desktop_credential_is_not_sent_to_remote_origin(tmp_path: Path) -> None:
    """A remote gateway never receives the machine-local desktop credential."""
    home = tmp_path / "app-home"
    home.mkdir()
    a2a_home = tmp_path / "a2a-home"
    _seed_desktop_authority(home, a2a_home, port=8123)
    with _settings_override(
        desktop_app_home=home,
        a2a_home=a2a_home,
        gateway_service_token=None,
    ):
        assert gateway_auth_headers("https://gateway.example:8123/v1/service") == {}


def _iter_options(command: click.Command) -> Iterator[click.Parameter]:
    """Yield every option across the whole CLI command tree."""
    yield from command.params
    if isinstance(command, click.Group):
        for sub in command.commands.values():
            yield from _iter_options(sub)


def test_no_cli_option_accepts_a_raw_secret() -> None:
    """No operator option accepts a secret value; secrets arrive only via files.

    A value-taking option whose name reads like a credential must be a path
    reference (``*-file``/``*-json``), never the secret itself.
    """
    secret_words = ("token", "secret", "password", "credential", "cred")
    offenders: list[str] = []
    for option in _iter_options(main):
        name = (option.name or "").lower()
        if not isinstance(option, click.Option):
            continue
        if not any(word in name for word in secret_words):
            continue
        # A boolean flag carries no value; a path reference names a file.
        if getattr(option, "is_flag", False):
            continue
        if name.endswith(("_file", "_json", "_path")):
            continue
        offenders.append(option.name or "<unnamed>")
    assert offenders == [], f"CLI options accept raw secrets: {offenders}"
