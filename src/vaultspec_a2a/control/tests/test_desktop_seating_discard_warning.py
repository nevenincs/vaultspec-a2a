"""Seating a desktop path over an explicit configuration must be audible.

The desktop profile is the single derivation authority for mutable paths, so it
overriding ``VAULTSPEC_DATABASE_URL`` is correct and stays correct — the precedence
is not what these tests pin. What they pin is that the override announces itself:
an operator who sets both an application home and an explicit database URL used to
get no diagnostic at all, and would look for their data in a file the process never
opened.

The signal has to stay rare to stay readable, so a field still holding its default
must produce no warning whatsoever. ``model_fields_set`` is the distinction, and
these tests drive it through real ``Settings`` construction over real environment
variables — the same path production takes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...control.config import Settings
from ...desktop.profile import derive_state_paths
from ...testing import armed_environment as _environment

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from pathlib import Path

    import pytest

_CONFIG_LOGGER = "vaultspec_a2a.control.config"

# Every environment name the desktop seating can displace, cleared by default so a
# developer's own environment cannot make an "untouched default" test lie.
_SEATED_NAMES = (
    "VAULTSPEC_DATABASE_URL",
    "VAULTSPEC_CHECKPOINT_DATABASE_URL",
    "VAULTSPEC_WORKSPACE_ROOT",
    "VAULTSPEC_A2A_HOME",
)


def _armed(app_home: Path, **explicit: str | None) -> AbstractContextManager[None]:
    """Return the environment for an armed desktop profile plus any explicit values."""
    values: dict[str, str | None] = dict.fromkeys(_SEATED_NAMES)
    values["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    values.update(explicit)
    return _environment(**values)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _CONFIG_LOGGER and record.levelno >= logging.WARNING
    ]


def test_an_explicit_database_url_discarded_by_seating_is_reported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The warning names the setting, the discarded value, and the derived one."""
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)
    supplied = "sqlite+aiosqlite:///operator-chosen.db"

    with (
        caplog.at_level(logging.WARNING, logger=_CONFIG_LOGGER),
        _armed(app_home, VAULTSPEC_DATABASE_URL=supplied),
    ):
        armed = Settings(_env_file=None)

    messages = _warnings(caplog)
    assert len(messages) == 1, messages
    assert "VAULTSPEC_DATABASE_URL" in messages[0]
    assert supplied in messages[0]
    assert state.database_path.as_posix() in messages[0]

    # The precedence itself is unchanged: the desktop derivation still wins.
    assert armed.database_url == f"sqlite+aiosqlite:///{state.database_path.as_posix()}"


def test_an_untouched_default_displaced_by_seating_stays_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Seating over a default is the normal case and must produce no warning."""
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)

    with caplog.at_level(logging.WARNING, logger=_CONFIG_LOGGER), _armed(app_home):
        armed = Settings(_env_file=None)

    assert _warnings(caplog) == []
    # Silence is not inaction: the seating still replaced every default.
    assert armed.database_url == f"sqlite+aiosqlite:///{state.database_path.as_posix()}"
    assert armed.workspace_root == state.workspaces_root
    assert armed.a2a_home == state.app_home


def test_every_displaced_setting_is_named_individually(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Four explicit settings displaced at once produce four distinct warnings."""
    app_home = tmp_path / "app"
    elsewhere = tmp_path / "elsewhere"

    with (
        caplog.at_level(logging.WARNING, logger=_CONFIG_LOGGER),
        _armed(
            app_home,
            VAULTSPEC_DATABASE_URL="sqlite+aiosqlite:///operator.db",
            VAULTSPEC_CHECKPOINT_DATABASE_URL="sqlite+aiosqlite:///operator-cp.db",
            VAULTSPEC_WORKSPACE_ROOT=str(elsewhere / "workspaces"),
            VAULTSPEC_A2A_HOME=str(elsewhere / "home"),
        ),
    ):
        Settings(_env_file=None)

    messages = _warnings(caplog)
    assert len(messages) == 4, messages
    for name in _SEATED_NAMES:
        assert any(name in message for message in messages), name


def test_an_unarmed_profile_never_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Without an application home nothing is displaced, so nothing is reported."""
    # Absolute: an unarmed profile has no seating to replace a relative URL, so a
    # relative one would be refused at construction before reaching this assertion.
    supplied = f"sqlite+aiosqlite:///{(tmp_path / 'operator.db').as_posix()}"

    with (
        caplog.at_level(logging.WARNING, logger=_CONFIG_LOGGER),
        _environment(
            VAULTSPEC_DESKTOP_APP_HOME=None,
            VAULTSPEC_DATABASE_URL=supplied,
        ),
    ):
        unarmed = Settings(_env_file=None)

    assert _warnings(caplog) == []
    assert unarmed.database_url == supplied
