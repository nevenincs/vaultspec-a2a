"""The session seat keeps every test artifact inside the worktree it runs from.

Each case seats a real session under a real temporary rootdir and reads the
process environment the seat leaves behind, restoring it afterwards.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ...control.infra_config import InfraConfig
from ...control.settings_base import env_name
from ..environment import armed_environment
from ..session_root import TEST_ROOT_NAME, TestSessionSettings, seat_test_session

_HOME = env_name(InfraConfig, "a2a_home")
_PROCS = env_name(InfraConfig, "procs_home")
_SEAT_NAMES = (
    _HOME,
    _PROCS,
    *(
        env_name(TestSessionSettings, field)
        for field in TestSessionSettings.model_fields
    ),
)


def _cleared(**values: str | None) -> dict[str, str | None]:
    names: dict[str, str | None] = dict.fromkeys(_SEAT_NAMES)
    names.update(values)
    return names


def test_a_fresh_seat_places_everything_under_the_rootdir(tmp_path: Path) -> None:
    with armed_environment(**_cleared()):
        seat = seat_test_session(tmp_path)
        home = os.environ[_HOME]
        procs = os.environ[_PROCS]

    root = tmp_path / TEST_ROOT_NAME
    assert seat.root.parent == root / "sessions"
    assert seat.basetemp == seat.root / "basetemp"
    assert Path(home) == seat.home and seat.home.is_dir()
    assert Path(procs) == root / "procs"


def test_seating_twice_in_one_process_returns_the_same_seat(tmp_path: Path) -> None:
    with armed_environment(**_cleared()):
        first = seat_test_session(tmp_path)
        second = seat_test_session(tmp_path)

    assert first.root == second.root


def test_a_home_the_caller_chose_is_respected(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen-home"
    with armed_environment(**_cleared(**{_HOME: str(chosen)})):
        seat_test_session(tmp_path / "root")
        home = os.environ[_HOME]

    assert Path(home) == chosen


def test_a_parents_seat_is_replaced_not_inherited(tmp_path: Path) -> None:
    """A nested controller must never run inside its parent's private seat."""
    parent_home = tmp_path / "parent" / "home"
    parent = _cleared(
        **{
            _HOME: str(parent_home),
            env_name(TestSessionSettings, "seated_home"): str(parent_home),
            env_name(TestSessionSettings, "session_root"): str(tmp_path / "parent"),
            env_name(TestSessionSettings, "session_pid"): str(os.getpid() + 1),
        }
    )
    with armed_environment(**parent):
        seat = seat_test_session(tmp_path / "nested")
        home = os.environ[_HOME]

    assert seat.root.is_relative_to(tmp_path / "nested")
    assert Path(home) == seat.home != parent_home


def test_a_nested_run_under_a_worker_marker_is_not_taken_for_a_worker(
    tmp_path: Path,
) -> None:
    """An inherited xdist marker alone does not make a process a worker."""
    code = (
        "import sys; from pathlib import Path; "
        "from vaultspec_a2a.testing.session_root import seat_test_session; "
        "print(seat_test_session(Path(sys.argv[1])).root)"
    )
    script = tmp_path / "nested_seat.py"
    script.write_text(code.replace("; ", "\n"), encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTEST_XDIST_WORKER"] = "gw0"
    environment[env_name(TestSessionSettings, "session_root")] = str(tmp_path / "p")
    environment[env_name(TestSessionSettings, "session_pid")] = "1"

    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "nested")],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    assert Path(completed.stdout.strip()).is_relative_to(tmp_path / "nested")
