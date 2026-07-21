"""Per-run config homes must honour the armed profile's declared root.

A packaged desktop install keeps its ephemeral homes inside its own application
home so an uninstall can account for them and a system-wide temporary sweep
cannot remove a home out from under a live run.  Every other profile stays on the
operating system temporary directory, where a sweep reclaiming an abandoned home
is a feature rather than a hazard.

The armed profile is exercised through the real settings object rather than a
stand-in, so the test fails if the profile seating changes shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...control.config import Settings
from ...desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from pathlib import Path


def test_the_unarmed_profile_declares_no_temporary_home_root() -> None:
    """Unarmed profiles leave the system temporary directory in charge."""
    settings = Settings()

    assert settings.desktop_temp_homes_dir is None


def test_the_armed_profile_declares_a_root_inside_its_application_home(
    tmp_path: Path,
) -> None:
    """An armed install keeps ephemeral homes under its own application home."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    settings = Settings(VAULTSPEC_DESKTOP_APP_HOME=app_home)

    resolved = settings.desktop_temp_homes_dir

    assert resolved is not None
    assert resolved == derive_state_paths(app_home).temp_homes_dir
    assert app_home in resolved.parents
