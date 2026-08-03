"""Real-construction tests for desktop-profile path seating in Settings.

Exercises the production ``Settings`` construction seam directly: no mocks,
monkeypatches, or settings mutation. Arming sets the application home through the
field's real environment variable exactly as production does, restoring the prior
environment afterwards.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ...control.config import Settings
from ...desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_APP_HOME_ENV = "VAULTSPEC_DESKTOP_APP_HOME"


@contextmanager
def _armed_env(app_home: str) -> Iterator[None]:
    """Set the desktop application-home environment variable, then restore it."""
    prior = os.environ.get(_APP_HOME_ENV)
    os.environ[_APP_HOME_ENV] = app_home
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(_APP_HOME_ENV, None)
        else:
            os.environ[_APP_HOME_ENV] = prior


def test_armed_profile_seats_every_mutable_path_under_app_home(tmp_path: Path) -> None:
    """Arming derives database, checkpoint, workspace, and A2A home from app home."""
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)

    with _armed_env(str(app_home)):
        armed = Settings()

    assert armed.desktop_app_home == app_home
    assert armed.a2a_home == state.app_home
    assert armed.workspace_root == state.workspaces_root
    assert armed.database_url == f"sqlite+aiosqlite:///{state.database_path.as_posix()}"
    assert armed.checkpoint_database_url == (
        f"sqlite+aiosqlite:///{state.checkpoint_path.as_posix()}"
    )


def test_armed_database_path_round_trips_to_app_home_seat(tmp_path: Path) -> None:
    """The derived sqlite URL resolves back to the app-home-seated database file."""
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)

    with _armed_env(str(app_home)):
        armed = Settings()

    assert armed.database_path == state.database_path
    assert armed.checkpoint_path == state.checkpoint_path
    assert armed.database_path.is_absolute()
    assert armed.database_path.is_relative_to(app_home)


def test_armed_profile_rejects_relative_app_home() -> None:
    """A launch-directory-relative application home fails construction loudly."""
    with (
        _armed_env("relative/app-home"),
        pytest.raises(ValidationError, match="absolute"),
    ):
        Settings()


def test_unarmed_profile_leaves_paths_untouched(tmp_path: Path) -> None:
    """Without an application home, path fields keep their configured values.

    The configured values are absolute because mutable paths must now be: a
    relative one is refused at construction rather than resolved against whatever
    working directory the process inherited. Only the seating is under test here —
    that rejection is pinned in ``test_absolute_path_requirement``.
    """
    baseline_db = (tmp_path / "baseline.db").as_posix()
    baseline_workspaces = tmp_path / "workspaces"

    unarmed = Settings(
        database_url=f"sqlite+aiosqlite:///{baseline_db}",
        workspace_root=baseline_workspaces,
    )

    assert unarmed.desktop_app_home is None
    assert unarmed.database_url == f"sqlite+aiosqlite:///{baseline_db}"
    assert unarmed.workspace_root == baseline_workspaces
