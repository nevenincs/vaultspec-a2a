"""A working-directory-relative store is refused, never quietly resolved.

A relative database URL or workspace root is a silent split-brain: the gateway and
the CLI resolve the same configured value against different working directories and
open different files, each convinced it holds the whole picture. The ruling is to
fail loud rather than relocate quietly.

Two things have to hold at once, and they pull in opposite directions:

* An explicitly supplied relative value must be REJECTED.
* The shipped defaults were themselves relative, and ``settings = Settings()`` runs
  at module import — so rejecting a default would make the package unimportable on
  a fresh checkout. An untouched default is therefore ANCHORED to the installation
  root instead, reproducing today's effective behaviour without the working-
  directory dependence.

Ordering is the other hazard. The desktop seating replaces all three values with
absolutes derived from the application home, so the check must observe the FINAL
resolved value; run earlier and a perfectly valid armed boot is rejected on the
relative default it was about to discard.
``test_an_armed_profile_overrides_even_a_relative_supplied_value`` is the guard on
that, verified by relocating the declaration and watching it fail.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ...control.config import Settings
from ...desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from collections.abc import Iterator

_PATH_NAMES = (
    "VAULTSPEC_DATABASE_URL",
    "VAULTSPEC_CHECKPOINT_DATABASE_URL",
    "VAULTSPEC_WORKSPACE_ROOT",
    "VAULTSPEC_DESKTOP_APP_HOME",
    "VAULTSPEC_PROJECT_ROOT",
)


@contextmanager
def _environment(**values: str | None) -> Iterator[None]:
    """Apply environment values (``None`` removes), then restore the prior state."""
    prior = {name: os.environ.get(name) for name in values}
    try:
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, previous in prior.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


@contextmanager
def _clean_environment(**values: str | None) -> Iterator[None]:
    """Clear every path setting, then apply the ones this test cares about."""
    cleared: dict[str, str | None] = dict.fromkeys(_PATH_NAMES)
    cleared.update(values)
    with _environment(**cleared):
        yield


def test_an_explicitly_relative_database_url_is_refused() -> None:
    """The message names the hazard, not just the rule."""
    with (
        _clean_environment(VAULTSPEC_DATABASE_URL="sqlite+aiosqlite:///vaultspec.db"),
        pytest.raises(ValidationError) as raised,
    ):
        Settings(_env_file=None)

    message = str(raised.value)
    assert "VAULTSPEC_DATABASE_URL must be absolute" in message
    assert "resolves against the process working directory" in message
    assert "silently open different files" in message


def test_an_explicitly_relative_checkpoint_url_is_refused() -> None:
    """The dedicated checkpoint store carries the identical defect class."""
    with (
        _clean_environment(
            VAULTSPEC_CHECKPOINT_DATABASE_URL="sqlite+aiosqlite:///checkpoints.db"
        ),
        pytest.raises(
            ValidationError, match="VAULTSPEC_CHECKPOINT_DATABASE_URL must be absolute"
        ),
    ):
        Settings(_env_file=None)


def test_an_explicitly_relative_workspace_root_is_refused() -> None:
    """The workspace root is launch-relative in exactly the same way."""
    with (
        _clean_environment(VAULTSPEC_WORKSPACE_ROOT="./workspaces"),
        pytest.raises(ValidationError) as raised,
    ):
        Settings(_env_file=None)

    message = str(raised.value)
    assert "VAULTSPEC_WORKSPACE_ROOT must be absolute" in message
    assert "silently open different directories" in message


def test_a_relative_value_is_rejected_rather_than_relocated() -> None:
    """Rejection, not repair: no absolute value is invented from a relative one."""
    with _clean_environment(VAULTSPEC_WORKSPACE_ROOT="./workspaces"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

        # The same construction with an absolute value succeeds untouched, which is
        # what makes the failure above a refusal rather than a missing feature.
        absolute = Path(os.getcwd()).resolve() / "workspaces"
        with _environment(VAULTSPEC_WORKSPACE_ROOT=str(absolute)):
            assert Settings(_env_file=None).workspace_root == absolute


def test_untouched_defaults_are_anchored_to_the_installation_root() -> None:
    """A bare construction must still succeed, with no working-directory dependence.

    ``settings = Settings()`` runs at module import, so this is the case that would
    brick a fresh checkout if the relative defaults were merely rejected.
    """
    with _clean_environment():
        settings = Settings(_env_file=None)

    project_root = settings.project_root
    assert project_root.is_absolute()
    assert settings.database_url == (
        f"sqlite+aiosqlite:///{(project_root / 'vaultspec.db').as_posix()}"
    )
    assert settings.workspace_root == project_root / "workspaces"
    assert settings.database_path == (project_root / "vaultspec.db").resolve()


def test_anchored_defaults_do_not_track_the_working_directory(tmp_path: Path) -> None:
    """Two launch directories must now resolve to the same store, not two.

    This is the defect stated as a test: the same configuration read from two
    working directories used to name two different database files.
    """
    launch_a = tmp_path / "launch-a"
    launch_b = tmp_path / "launch-b"
    launch_a.mkdir()
    launch_b.mkdir()
    prior = Path.cwd()

    with _clean_environment():
        try:
            os.chdir(launch_a)
            from_a = Settings(_env_file=None)
            os.chdir(launch_b)
            from_b = Settings(_env_file=None)
        finally:
            os.chdir(prior)

    assert from_a.database_path == from_b.database_path
    assert from_a.workspace_root == from_b.workspace_root
    assert not from_a.database_path.is_relative_to(launch_a.resolve())


def test_the_anchor_is_the_overridable_project_root_field(tmp_path: Path) -> None:
    """Anchoring follows ``VAULTSPEC_PROJECT_ROOT``, not the ``__file__`` constant.

    A non-editable container install resolves the ``__file__``-derived constant into
    site-packages and corrects it through this variable, so anchoring to the
    constant would place the container's default stores inside site-packages.
    """
    elsewhere = tmp_path / "install-root"
    elsewhere.mkdir()

    with _clean_environment(VAULTSPEC_PROJECT_ROOT=str(elsewhere)):
        settings = Settings(_env_file=None)

    assert settings.workspace_root == elsewhere / "workspaces"
    assert settings.database_url == (
        f"sqlite+aiosqlite:///{(elsewhere / 'vaultspec.db').as_posix()}"
    )


def test_a_relative_project_root_is_refused_with_its_own_message() -> None:
    """The anchor itself must be absolute, or the anchored defaults are not."""
    with (
        _clean_environment(VAULTSPEC_PROJECT_ROOT="./somewhere"),
        pytest.raises(ValidationError, match="VAULTSPEC_PROJECT_ROOT must be absolute"),
    ):
        Settings(_env_file=None)


def test_an_armed_desktop_profile_still_constructs(tmp_path: Path) -> None:
    """The armed profile boots on the relative default and replaces it.

    Written as a ``@field_validator`` the check would fire before any model
    validator — before the seating and before the anchoring — and reject this
    construction on the default it was about to discard, breaking every packaged
    desktop launch. The sharper ordering guard is the test below.
    """
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)

    with _clean_environment(VAULTSPEC_DESKTOP_APP_HOME=str(app_home)):
        armed = Settings(_env_file=None)

    assert armed.database_url == f"sqlite+aiosqlite:///{state.database_path.as_posix()}"
    assert armed.workspace_root == state.workspaces_root
    assert armed.database_path.is_relative_to(app_home)


def test_an_armed_profile_overrides_even_a_relative_supplied_value(
    tmp_path: Path,
) -> None:
    """THE ordering guard. Seating displaces the value before it is ever checked.

    The operator is still told — the seating warns that the value was discarded —
    but the boot succeeds, because the value the process will actually use is the
    derived absolute one. Moving this validator ahead of ``_seat_desktop_profile``
    turns this into a hard failure over a setting the desktop profile ignores by
    design; verified by relocating the declaration, at which point only this test
    fails.
    """
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)

    with _clean_environment(
        VAULTSPEC_DESKTOP_APP_HOME=str(app_home),
        VAULTSPEC_DATABASE_URL="sqlite+aiosqlite:///vaultspec.db",
        VAULTSPEC_WORKSPACE_ROOT="./workspaces",
    ):
        armed = Settings(_env_file=None)

    assert armed.database_url == f"sqlite+aiosqlite:///{state.database_path.as_posix()}"
    assert armed.workspace_root == state.workspaces_root


def test_an_absolute_posix_path_is_accepted_on_any_host() -> None:
    """A container configuration must validate on a developer workstation too.

    These settings name paths on the deployment host. ``/app/data/vaultspec.db`` is
    the value every Compose file ships; ``pathlib`` on Windows calls it relative, so
    a local-flavour check would reject the project's own production configuration.
    """
    with _clean_environment(
        VAULTSPEC_DATABASE_URL="sqlite+aiosqlite:////app/data/vaultspec.db",
        VAULTSPEC_WORKSPACE_ROOT="/app/workspaces",
        VAULTSPEC_PROJECT_ROOT="/app",
    ):
        settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite:////app/data/vaultspec.db"


def test_postgres_urls_are_exempt_from_the_absolute_requirement() -> None:
    """A Postgres path component names a database on a server, not a file."""
    url = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/vaultspec"

    with (
        _clean_environment(
            VAULTSPEC_DATABASE_URL=url,
            VAULTSPEC_WORKSPACE_ROOT=str(Path.cwd().resolve() / "workspaces"),
        ),
        _environment(
            VAULTSPEC_DATABASE_BACKEND="postgres",
            VAULTSPEC_CHECKPOINT_BACKEND="postgres",
        ),
    ):
        settings = Settings(_env_file=None)

    assert settings.database_url == url


def test_an_in_memory_sqlite_url_is_exempt() -> None:
    """``:memory:`` names no file, so no working directory can relocate it."""
    with _clean_environment(
        VAULTSPEC_DATABASE_URL="sqlite+aiosqlite:///:memory:",
        VAULTSPEC_WORKSPACE_ROOT=str(Path.cwd().resolve() / "workspaces"),
    ):
        settings = Settings(_env_file=None)

    assert settings.database_path == Path(":memory:")


def test_backend_and_url_disagreement_is_refused_at_construction() -> None:
    """The moved agreement check must stay enforced, and stay enforced at boot.

    It used to live in the synchronous-URL properties as a discarded binding, read
    purely for its raising side effect — invisible as load-bearing and one cleanup
    away from deletion. It now decides whether the absolute-path check applies at
    all, so it is consumed rather than discarded. This pins the behaviour that move
    must preserve: the synchronous admin engines have no other validation seam.
    """
    with (
        _clean_environment(
            VAULTSPEC_DATABASE_URL="sqlite+aiosqlite:////app/data/vaultspec.db"
        ),
        _environment(VAULTSPEC_DATABASE_BACKEND="postgres"),
        pytest.raises(ValidationError, match="VAULTSPEC_DATABASE_BACKEND=postgres"),
    ):
        Settings(_env_file=None)


def test_a_postgres_backend_declared_over_a_sqlite_checkpoint_is_refused() -> None:
    """The checkpoint store is held to the same agreement as the primary one."""
    with (
        _clean_environment(
            VAULTSPEC_CHECKPOINT_DATABASE_URL="sqlite+aiosqlite:////app/cp.db"
        ),
        _environment(VAULTSPEC_CHECKPOINT_BACKEND="postgres"),
        pytest.raises(ValidationError, match="VAULTSPEC_CHECKPOINT_BACKEND=postgres"),
    ):
        Settings(_env_file=None)
