"""The armed desktop profile models three distinct credential references."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from vaultspec_a2a.control.config import Settings
from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
    WORKER_IPC_CREDENTIAL_NAME,
)
from vaultspec_a2a.desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from pathlib import Path


def _app_home(tmp_path: Path) -> Path:
    """Return an absolute application home under a real temp directory."""
    home = tmp_path / "app-home"
    home.mkdir()
    return home


def test_unarmed_profile_exposes_no_credential_references() -> None:
    """The Compose and development profiles surface no credential paths."""
    settings = Settings(VAULTSPEC_DESKTOP_APP_HOME=None)
    assert settings.desktop_credential_paths is None


def test_armed_profile_models_three_distinct_planes(tmp_path: Path) -> None:
    """Arming the profile derives distinct attach, ownership, and worker IPC paths."""
    home = _app_home(tmp_path)
    settings = Settings(VAULTSPEC_DESKTOP_APP_HOME=str(home))

    references = settings.desktop_credential_paths
    assert references is not None

    state = derive_state_paths(home)
    assert references.credentials_dir == state.credentials_dir
    assert references.attach_path == state.credentials_dir / ATTACH_CREDENTIAL_NAME
    assert (
        references.ownership_path == state.credentials_dir / OWNERSHIP_CAPABILITY_NAME
    )
    assert (
        references.worker_ipc_path == state.credentials_dir / WORKER_IPC_CREDENTIAL_NAME
    )
    assert (
        len(
            {
                references.attach_path,
                references.ownership_path,
                references.worker_ipc_path,
            }
        )
        == 3
    )


def test_credential_references_are_app_home_seated(tmp_path: Path) -> None:
    """Every credential path lives beneath the explicit application home."""
    home = _app_home(tmp_path)
    settings = Settings(VAULTSPEC_DESKTOP_APP_HOME=str(home))

    references = settings.desktop_credential_paths
    assert references is not None
    for path in (
        references.attach_path,
        references.ownership_path,
        references.worker_ipc_path,
    ):
        assert path.is_absolute()
        assert str(path).startswith(str(home))


def test_unarmed_reference_lookup_does_not_import_desktop_credentials() -> None:
    """Reading the reference while unarmed never pulls the desktop package.

    The unarmed import surface is a stated invariant: the property must short
    circuit before importing the desktop credential module.
    """
    sys.modules.pop("vaultspec_a2a.desktop.credentials", None)
    settings = Settings(VAULTSPEC_DESKTOP_APP_HOME=None)
    assert settings.desktop_credential_paths is None
    assert "vaultspec_a2a.desktop.credentials" not in sys.modules
