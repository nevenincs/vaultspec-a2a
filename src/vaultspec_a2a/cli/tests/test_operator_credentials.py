"""Operator calls read owner-scoped credential files, never secret arguments."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import click

from vaultspec_a2a.cli.main import _read_desktop_attach_credential, main
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.desktop._platform_acl import harden_credential_file
from vaultspec_a2a.desktop.credentials import ATTACH_CREDENTIAL_NAME
from vaultspec_a2a.desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_TOKEN = "attach-credential-token-a0b1c2d3e4f5a6b7"


@contextmanager
def _settings_override(**updates: object) -> Iterator[None]:
    originals = {name: getattr(settings, name) for name in updates}
    for name, value in updates.items():
        setattr(settings, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(settings, name, value)


def _seed_attach_file(app_home: Path) -> None:
    """Write the dashboard-created attach credential under the app home."""
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    attach = state.credentials_dir / ATTACH_CREDENTIAL_NAME
    attach.write_text(_TOKEN, encoding="utf-8")
    harden_credential_file(attach)


def test_reads_attach_credential_when_armed(tmp_path: Path) -> None:
    """An armed operator reads the owner-scoped attach credential file."""
    home = tmp_path / "app-home"
    home.mkdir()
    _seed_attach_file(home)
    with _settings_override(desktop_app_home=home):
        assert _read_desktop_attach_credential() == _TOKEN


def test_returns_none_when_unarmed() -> None:
    """The unarmed profile reads no credential file."""
    with _settings_override(desktop_app_home=None):
        assert _read_desktop_attach_credential() is None


def test_returns_none_when_file_absent(tmp_path: Path) -> None:
    """An armed profile with no attach file falls through rather than raising."""
    home = tmp_path / "app-home"
    home.mkdir()
    with _settings_override(desktop_app_home=home):
        assert _read_desktop_attach_credential() is None


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
