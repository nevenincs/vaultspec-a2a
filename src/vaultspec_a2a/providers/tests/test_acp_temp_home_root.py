"""Per-run config homes live inside the state home, whatever the profile.

Every profile keeps its ephemeral homes inside its own state home, so they are
accounted for with the rest of a2a's state and a system-wide temporary sweep
cannot remove a home out from under a live run. Nothing is created in the
operating system's temporary directory independently of the configured state home.

Both profiles are exercised through the real settings object rather than a
stand-in, so the test fails if the layout or the seating changes shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...control.config import Settings
from ...desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from pathlib import Path


def test_the_default_profile_keeps_temporary_homes_in_its_state_home() -> None:
    settings = Settings()

    root = settings.temp_homes_dir

    assert root == settings.a2a_home / "tmp" / "homes"
    # The configured state home may itself be under the OS temporary parent,
    # including in a disposable checkout. Ownership follows the explicit home.
    assert root.is_relative_to(settings.a2a_home)


def test_the_armed_profile_keeps_them_inside_its_application_home(
    tmp_path: Path,
) -> None:
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    settings = Settings(desktop_app_home=app_home)

    resolved = settings.temp_homes_dir

    assert resolved == derive_state_paths(app_home).temp_homes_dir
    assert app_home in resolved.parents
