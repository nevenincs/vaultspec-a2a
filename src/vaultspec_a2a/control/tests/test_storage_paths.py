"""Every path setting resolves against the project root, never the launch folder.

A working-directory-relative store is a silent split-brain: the gateway and the
CLI resolve the same configured value against different working directories and
open different files, each convinced it holds the whole picture. The rule that
removes it is to have ONE anchor for every relative path - the project root - and
to accept relative and absolute values alike under it.

The state home's own default is the relative ``.vault/data/agents``, so the
default lands in the project by the same rule an operator's relative value does,
and both stores default into its ``state/`` directory.

Each case builds a real ``Settings`` against a real temporary project, with the
dotenv lookup disabled so a developer's own ``.env`` cannot colour the result.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest
from pydantic import ValidationError

from ...control.config import Settings
from ...desktop.profile import derive_state_paths
from ...testing import armed_environment as _environment
from ..state_layout import DEFAULT_HOME

if TYPE_CHECKING:
    from collections.abc import Generator

_PATH_NAMES = (
    "VAULTSPEC_A2A_DATABASE_URL",
    "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
    "VAULTSPEC_A2A_WORKSPACE_ROOT",
    "VAULTSPEC_A2A_DESKTOP_APP_HOME",
    "VAULTSPEC_A2A_INSTALL_ROOT",
    "VAULTSPEC_A2A_HOME",
    "VAULTSPEC_A2A_PROCS_HOME",
    "VAULTSPEC_A2A_PROCS_TOML",
    "VAULTSPEC_A2A_ENGINE_SERVICE_JSON",
    "VAULTSPEC_A2A_DATABASE_BACKEND",
    "VAULTSPEC_A2A_CHECKPOINT_BACKEND",
)


class _SettingsEnvFileFactory(Protocol):
    def __call__(self, *, _env_file: Path | None) -> Settings: ...


def _settings() -> Settings:
    """Construct with dotenv discovery disabled, typed for the type checker."""
    return cast("_SettingsEnvFileFactory", Settings)(_env_file=None)


@contextmanager
def _project(root: Path, **values: str | None) -> Generator[Path]:
    """Serve ``root`` as the project, with every path setting cleared first."""
    root.mkdir(parents=True, exist_ok=True)
    cleared: dict[str, str | None] = dict.fromkeys(_PATH_NAMES)
    cleared["VAULTSPEC_A2A_PROJECT_ROOT"] = str(root)
    cleared.update(values)
    with _environment(**cleared):
        yield root


def _sqlite(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def test_the_default_home_and_stores_live_in_the_project(tmp_path: Path) -> None:
    with _project(tmp_path / "project") as root:
        settings = _settings()

    home = root / DEFAULT_HOME
    assert settings.a2a_home == home
    assert settings.database_url == _sqlite(home / "state" / "vaultspec.db")
    assert settings.checkpoint_database_url == _sqlite(
        home / "state" / "checkpoints.db"
    )
    assert settings.state_layout.logs_dir == home / "runtime"
    assert settings.state_layout.discovery_path == home / "service.json"
    # The workspace root carries no default: it is a label, not a store.
    assert settings.workspace_root is None


def test_a_relative_home_resolves_against_the_project_not_the_launch_folder(
    tmp_path: Path,
) -> None:
    """Two launch folders, one configuration, one store - the defect as a test."""
    launch_a = tmp_path / "launch-a"
    launch_b = tmp_path / "launch-b"
    launch_a.mkdir()
    launch_b.mkdir()
    prior = Path.cwd()

    with _project(tmp_path / "project", VAULTSPEC_A2A_HOME="state-here") as root:
        try:
            os.chdir(launch_a)
            from_a = _settings()
            os.chdir(launch_b)
            from_b = _settings()
        finally:
            os.chdir(prior)

    assert from_a.a2a_home == from_b.a2a_home == root / "state-here"
    assert from_a.database_url == from_b.database_url
    assert not from_a.database_path.is_relative_to(launch_a.resolve())


def test_an_absolute_home_is_taken_as_is_and_carries_the_stores(
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "elsewhere"
    with _project(tmp_path / "project", VAULTSPEC_A2A_HOME=str(elsewhere)):
        settings = _settings()

    assert settings.a2a_home == elsewhere
    assert settings.database_url == _sqlite(elsewhere / "state" / "vaultspec.db")


def test_a_relative_sqlite_url_resolves_against_the_project(tmp_path: Path) -> None:
    """A configured database keeps the one-store arrangement it always had."""
    with _project(
        tmp_path / "project",
        VAULTSPEC_A2A_DATABASE_URL="sqlite+aiosqlite:///data/store.db",
    ) as root:
        settings = _settings()

    assert settings.database_url == _sqlite(root / "data" / "store.db")
    assert settings.checkpoint_database_url is None
    assert settings.checkpoint_path == (root / "data" / "store.db").resolve()


def test_a_relative_checkpoint_url_resolves_against_the_project(
    tmp_path: Path,
) -> None:
    with _project(
        tmp_path / "project",
        VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL="sqlite+aiosqlite:///cp.db",
    ) as root:
        settings = _settings()

    assert settings.checkpoint_database_url == _sqlite(root / "cp.db")


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("VAULTSPEC_A2A_WORKSPACE_ROOT", "workspace_root"),
        ("VAULTSPEC_A2A_PROCS_HOME", "procs_home"),
        ("VAULTSPEC_A2A_PROCS_TOML", "procs_toml"),
        ("VAULTSPEC_A2A_ENGINE_SERVICE_JSON", "engine_service_json"),
    ],
)
def test_every_other_path_setting_follows_the_same_rule(
    tmp_path: Path, name: str, field: str
) -> None:
    with _project(tmp_path / "project", **{name: "relative/value"}) as root:
        settings = _settings()

    assert getattr(settings, field) == root / "relative" / "value"


def test_an_absolute_posix_path_is_accepted_on_any_host(tmp_path: Path) -> None:
    """A container configuration must validate on a developer workstation too."""
    with _project(
        tmp_path / "project",
        VAULTSPEC_A2A_DATABASE_URL="sqlite+aiosqlite:////app/data/vaultspec.db",
        VAULTSPEC_A2A_WORKSPACE_ROOT="/app/workspaces",
        VAULTSPEC_A2A_HOME="/app/state",
    ):
        settings = _settings()

    assert settings.database_url == "sqlite+aiosqlite:////app/data/vaultspec.db"
    assert settings.a2a_home == Path("/app/state")


def test_server_and_in_memory_urls_are_left_alone(tmp_path: Path) -> None:
    url = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/vaultspec"
    with _project(
        tmp_path / "project",
        VAULTSPEC_A2A_DATABASE_URL=url,
        VAULTSPEC_A2A_DATABASE_BACKEND="postgres",
        VAULTSPEC_A2A_CHECKPOINT_BACKEND="postgres",
    ):
        assert _settings().database_url == url

    with _project(
        tmp_path / "project",
        VAULTSPEC_A2A_DATABASE_URL="sqlite+aiosqlite:///:memory:",
    ):
        assert _settings().database_path == Path(":memory:")


def test_backend_and_url_disagreement_is_refused_at_construction(
    tmp_path: Path,
) -> None:
    """The synchronous admin engines have no other seam to catch this."""
    with (
        _project(
            tmp_path / "project",
            VAULTSPEC_A2A_DATABASE_URL="sqlite+aiosqlite:////app/data/vaultspec.db",
            VAULTSPEC_A2A_DATABASE_BACKEND="postgres",
        ),
        pytest.raises(ValidationError, match="VAULTSPEC_A2A_DATABASE_BACKEND=postgres"),
    ):
        _settings()


def test_a_postgres_checkpoint_backend_over_a_sqlite_default_is_refused(
    tmp_path: Path,
) -> None:
    """The defaulted checkpoint store is held to the same agreement."""
    with (
        _project(tmp_path / "project", VAULTSPEC_A2A_CHECKPOINT_BACKEND="postgres"),
        pytest.raises(
            ValidationError, match="VAULTSPEC_A2A_CHECKPOINT_BACKEND=postgres"
        ),
    ):
        _settings()


def test_an_armed_desktop_profile_seats_everything_under_its_home(
    tmp_path: Path,
) -> None:
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)

    with _project(
        tmp_path / "project",
        VAULTSPEC_A2A_DESKTOP_APP_HOME=str(app_home),
        VAULTSPEC_A2A_DATABASE_URL="sqlite+aiosqlite:///vaultspec.db",
        VAULTSPEC_A2A_WORKSPACE_ROOT="./workspaces",
    ):
        armed = _settings()

    assert armed.a2a_home == app_home
    assert armed.database_url == _sqlite(state.database_path)
    assert armed.checkpoint_database_url == _sqlite(state.checkpoint_path)
    assert armed.workspace_root == state.workspaces_root


def test_a_relative_desktop_app_home_resolves_against_the_project(
    tmp_path: Path,
) -> None:
    with _project(
        tmp_path / "project", VAULTSPEC_A2A_DESKTOP_APP_HOME="app-home"
    ) as root:
        armed = _settings()

    assert armed.a2a_home == root / "app-home"
    assert armed.database_path.is_relative_to(root / "app-home")


def test_the_defaults_do_not_depend_on_a_discoverable_dotenv(tmp_path: Path) -> None:
    """Same project, with and without dotenv discovery, launched from two folders."""
    prior = Path.cwd()
    resolved: list[str] = []

    with _project(tmp_path / "project"):
        try:
            for directory in (prior, tmp_path):
                os.chdir(directory)
                resolved.append(_settings().database_url)
                resolved.append(Settings().database_url)
        finally:
            os.chdir(prior)

    assert len(set(resolved)) == 1, resolved
