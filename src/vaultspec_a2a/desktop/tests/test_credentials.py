"""Real-file certification of the split desktop credential authority."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from vaultspec_a2a.desktop._platform_acl import (
    credential_file_is_owner_restricted,
    harden_credential_file,
)
from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
    WORKER_IPC_CREDENTIAL_NAME,
    CredentialError,
    create_worker_ipc_credential,
    credential_paths,
    load_attach_credential,
    load_ownership_capability,
)

_VALID_TOKEN = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def _write_restricted(directory: Path, name: str, content: str) -> Path:
    """Write an owner-restricted credential file the way the dashboard would."""
    path = directory / name
    path.write_text(content, encoding="utf-8")
    harden_credential_file(path)
    return path


def test_credential_paths_layout(tmp_path: Path) -> None:
    """The three planes derive distinct files under the credentials directory."""
    paths = credential_paths(tmp_path)
    assert paths.attach_path == tmp_path / ATTACH_CREDENTIAL_NAME
    assert paths.ownership_path == tmp_path / OWNERSHIP_CAPABILITY_NAME
    assert paths.worker_ipc_path == tmp_path / WORKER_IPC_CREDENTIAL_NAME
    assert len({paths.attach_path, paths.ownership_path, paths.worker_ipc_path}) == 3


def test_load_attach_and_ownership_round_trip(tmp_path: Path) -> None:
    """A well-formed owner-restricted file loads back verbatim, per plane."""
    _write_restricted(tmp_path, ATTACH_CREDENTIAL_NAME, _VALID_TOKEN)
    _write_restricted(tmp_path, OWNERSHIP_CAPABILITY_NAME, _VALID_TOKEN + "ffff")

    assert load_attach_credential(tmp_path) == _VALID_TOKEN
    assert load_ownership_capability(tmp_path) == _VALID_TOKEN + "ffff"


def test_attach_loader_is_plane_scoped(tmp_path: Path) -> None:
    """The attach loader reads only the attach file, never the ownership file."""
    _write_restricted(tmp_path, OWNERSHIP_CAPABILITY_NAME, _VALID_TOKEN)
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    """An absent credential file is a typed fail-closed error."""
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


def test_empty_file_rejected(tmp_path: Path) -> None:
    """An empty credential file is rejected."""
    _write_restricted(tmp_path, ATTACH_CREDENTIAL_NAME, "   \n")
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


def test_short_token_rejected(tmp_path: Path) -> None:
    """A token below the minimum length is rejected."""
    _write_restricted(tmp_path, ATTACH_CREDENTIAL_NAME, "abc123")
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


def test_bad_charset_rejected(tmp_path: Path) -> None:
    """A token carrying whitespace or control characters is rejected."""
    _write_restricted(tmp_path, ATTACH_CREDENTIAL_NAME, _VALID_TOKEN + " tail")
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


def test_oversized_file_rejected(tmp_path: Path) -> None:
    """A file beyond the size bound is rejected before its bytes are trusted."""
    _write_restricted(tmp_path, ATTACH_CREDENTIAL_NAME, "a" * (4096 + 10))
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


def test_directory_in_place_of_file_rejected(tmp_path: Path) -> None:
    """A non-regular path at the credential name is rejected."""
    (tmp_path / ATTACH_CREDENTIAL_NAME).mkdir()
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission-bit enforcement")
def test_group_readable_file_rejected(tmp_path: Path) -> None:
    """A group- or world-accessible file is not owner-restricted and is rejected."""
    path = tmp_path / ATTACH_CREDENTIAL_NAME
    path.write_text(_VALID_TOKEN, encoding="utf-8")
    os.chmod(path, 0o644)
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_symlinked_credential_rejected(tmp_path: Path) -> None:
    """A symlink standing in for the credential file is rejected."""
    real = tmp_path / "real_secret"
    real.write_text(_VALID_TOKEN, encoding="utf-8")
    harden_credential_file(real)
    link = tmp_path / ATTACH_CREDENTIAL_NAME
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")
    with pytest.raises(CredentialError):
        load_attach_credential(tmp_path)


def test_create_worker_ipc_credential_round_trip(tmp_path: Path) -> None:
    """The gateway mints an owner-restricted worker IPC secret it can read back."""
    credentials_dir = tmp_path / "credentials"
    secret = create_worker_ipc_credential(credentials_dir)

    assert len(secret) == 64
    assert all(char in "0123456789abcdef" for char in secret)

    worker_path = credential_paths(credentials_dir).worker_ipc_path
    assert worker_path.is_file()
    assert credential_file_is_owner_restricted(worker_path)
    assert worker_path.read_text(encoding="utf-8") == secret


def test_create_worker_ipc_credential_is_per_boot(tmp_path: Path) -> None:
    """Each mint replaces the prior secret rather than reusing it."""
    credentials_dir = tmp_path / "credentials"
    first = create_worker_ipc_credential(credentials_dir)
    second = create_worker_ipc_credential(credentials_dir)
    assert first != second
    worker_path = credential_paths(credentials_dir).worker_ipc_path
    assert worker_path.read_text(encoding="utf-8") == second
