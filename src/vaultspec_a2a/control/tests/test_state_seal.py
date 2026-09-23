"""The state home is invisible to version control in any project.

The default home sits inside the project a2a serves. A vaultspec project already
ignores ``.vault/data``, but a plain repository does not, and the home holds the
gateway's handoff credential and copies of provider logins. These tests drive a
real ``git`` over a real repository with no vaultspec marker at all.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING, Protocol, cast

from ...cli.service import setup_service
from ...lifecycle.singleton import acquire_singleton
from ...testing import armed_environment
from ..config import Settings
from ..settings_base import PROJECT_ROOT_ENV
from ..state_layout import SEAL_FILE, seal_state_home

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which("git")


class _SettingsEnvFileFactory(Protocol):
    def __call__(self, *, _env_file: Path | None) -> Settings: ...


def _settings_for(project: Path) -> Settings:
    with armed_environment(
        **{PROJECT_ROOT_ENV: str(project), "VAULTSPEC_A2A_HOME": None}
    ):
        return cast("_SettingsEnvFileFactory", Settings)(_env_file=None)


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


def test_a_directory_outside_the_home_does_not_seal_it(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path / "project")

    settings.prepare_state_dir(tmp_path / "elsewhere")

    assert not (settings.a2a_home / SEAL_FILE).exists()


def test_sealing_is_idempotent_and_keeps_the_first_seal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seal_state_home(home)
    first = (home / SEAL_FILE).read_text(encoding="utf-8")

    seal_state_home(home)

    assert (home / SEAL_FILE).read_text(encoding="utf-8") == first
    assert "*" in first.splitlines()
