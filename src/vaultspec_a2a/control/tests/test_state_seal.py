"""The state home is invisible to version control in any project.

The default home sits inside the project a2a serves. A vaultspec project already
ignores ``.vault/data``, but a plain repository does not, and the home holds the
gateway's handoff credential and copies of provider logins. These tests drive a
real ``git`` over a real repository with no vaultspec marker at all.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import TYPE_CHECKING, Protocol, cast

import pytest
from pydantic import ValidationError

from ...cli.service import setup_service
from ...lifecycle.singleton import acquire_singleton
from ...testing import armed_environment
from ..config import Settings
from ..settings_base import PROJECT_ROOT_ENV
from ..state_layout import SEAL_FILE, UnsafeStateHomeError, seal_state_home

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which("git")


class _SettingsEnvFileFactory(Protocol):
    def __call__(self, *, _env_file: Path | None) -> Settings: ...


def _settings_for(project: Path, home: str | None = None) -> Settings:
    with armed_environment(
        **{PROJECT_ROOT_ENV: str(project), "VAULTSPEC_A2A_HOME": home}
    ):
        return cast("_SettingsEnvFileFactory", Settings)(_env_file=None)


def _git_repository(tmp_path: Path) -> Path:
    project = tmp_path / "plain-repo"
    project.mkdir()
    _git(project, "init", "-q")
    return project


def _git(project: Path, *args: str) -> str:
    assert _GIT is not None, "git is a development prerequisite of this repository"
    completed = subprocess.run(
        [_GIT, *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def test_state_written_into_a_plain_repository_stays_untracked(tmp_path: Path) -> None:
    project = tmp_path / "plain-repo"
    project.mkdir()
    _git(project, "init", "-q")
    settings = _settings_for(project)

    logs = settings.prepare_state_dir(settings.state_layout.logs_dir)
    (logs / "gateway.log").write_text("line\n", encoding="utf-8")
    settings.state_layout.handoff_credential_path.write_text("bearer", "utf-8")

    assert settings.a2a_home.is_relative_to(project)
    assert _git(project, "status", "--porcelain", "--untracked-files=all") == ""


def test_setup_and_the_runtime_lock_leave_a_plain_repository_clean(
    tmp_path: Path,
) -> None:
    """The store initialiser and the singleton write before any serve does."""
    project = tmp_path / "plain-repo"
    project.mkdir()
    _git(project, "init", "-q")
    home = _settings_for(project).a2a_home

    result = setup_service(home)
    with acquire_singleton(home):
        pass

    assert result["status"] == "succeeded", result
    assert (home / "state").is_dir()
    assert _git(project, "status", "--porcelain", "--untracked-files=all") == ""


def test_a_directory_outside_the_project_is_left_unsealed(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path / "project")
    elsewhere = tmp_path / "elsewhere"

    settings.prepare_state_dir(elsewhere / "store")

    assert elsewhere.is_dir()
    assert not (settings.a2a_home / SEAL_FILE).exists()
    assert not (elsewhere / SEAL_FILE).exists()


def test_a_store_relocated_inside_the_project_stays_untracked(tmp_path: Path) -> None:
    """A relocated store is sealed where a2a starts creating directories for it."""
    project = _git_repository(tmp_path)
    settings = _settings_for(project)

    registry = settings.prepare_state_dir(project / "local-state" / "procs")
    (registry / "scratch-18000.reserved").write_text("1234", encoding="utf-8")

    assert (project / "local-state" / SEAL_FILE).is_file()
    assert _git(project, "status", "--porcelain", "--untracked-files=all") == ""


def test_an_existing_operator_directory_gets_no_ignore_file(tmp_path: Path) -> None:
    """a2a writes an ignore file only into a directory it created itself."""
    project = _git_repository(tmp_path)
    operator_dir = project / "data"
    operator_dir.mkdir()
    settings = _settings_for(project)

    settings.prepare_state_dir(operator_dir / "stores")

    assert not (operator_dir / SEAL_FILE).exists()
    assert (operator_dir / "stores" / SEAL_FILE).is_file()


@pytest.mark.parametrize("home", [".", ".."], ids=["project-root", "ancestor"])
def test_a_state_home_that_holds_the_project_is_refused(
    tmp_path: Path, home: str
) -> None:
    project = _git_repository(tmp_path)

    with pytest.raises(ValidationError, match="contains the project root"):
        _settings_for(project, home=home)

    assert not (project / SEAL_FILE).exists()


def test_a_repository_root_is_never_sealed(tmp_path: Path) -> None:
    """Even a home handed straight to a writer is refused when it is a repository."""
    other = _git_repository(tmp_path)

    with pytest.raises(UnsafeStateHomeError, match="root of a repository"):
        seal_state_home(other)

    assert not (other / SEAL_FILE).exists()
    assert _git(other, "status", "--porcelain", "--untracked-files=all") == ""


def test_sealing_is_idempotent_and_keeps_the_first_seal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seal_state_home(home)
    first = (home / SEAL_FILE).read_text(encoding="utf-8")

    seal_state_home(home)

    assert (home / SEAL_FILE).read_text(encoding="utf-8") == first
    assert "*" in first.splitlines()


def test_an_operator_directory_named_as_home_is_never_sealed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A tracked source directory chosen as the home keeps tracking new files."""
    project = _git_repository(tmp_path)
    source = project / "src"
    source.mkdir()
    (source / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    settings = _settings_for(project, home="src")

    with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.control.state_layout"):
        settings.prepare_state_dir(settings.state_layout.logs_dir)
    (source / "new_module.py").write_text("y = 2\n", encoding="utf-8")

    assert not (source / SEAL_FILE).exists()
    assert "?? src/new_module.py" in _git(
        project, "status", "--porcelain", "--untracked-files=all"
    )
    assert any(
        "already holds files a2a did not write" in r.message for r in caplog.records
    )


def test_an_existing_home_holding_only_a2a_state_is_sealed(tmp_path: Path) -> None:
    """A home written before homes were sealed is recognisably a2a's own."""
    project = _git_repository(tmp_path)
    home = project / "legacy-home"
    (home / "state").mkdir(parents=True)
    (home / "state" / "vaultspec.db").write_bytes(b"")
    (home / "service.json").write_text("{}", encoding="utf-8")
    (home / "service.json.4242.tmp").write_text("{}", encoding="utf-8")

    seal_state_home(home)

    assert (home / SEAL_FILE).is_file()
    assert _git(project, "status", "--porcelain", "--untracked-files=all") == ""


def test_an_existing_empty_home_is_sealed(tmp_path: Path) -> None:
    home = tmp_path / "prepared-by-a-launcher"
    home.mkdir()

    seal_state_home(home)

    assert (home / SEAL_FILE).is_file()
