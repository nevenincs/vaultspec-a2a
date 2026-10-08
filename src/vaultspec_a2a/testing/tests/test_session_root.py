"""The session seat keeps every test artifact inside the worktree it runs from.

Each case seats a real session under a real temporary rootdir and reads the
process environment the seat leaves behind, restoring it afterwards.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from ...control.infra_config import InfraConfig
from ...control.settings_base import env_name
from .. import harness_names
from ..cli import inherited_environment
from ..environment import armed_environment
from ..session_root import (
    TEST_ROOT_NAME,
    TestSessionSettings,
    prune_stale_dirs,
    seat_test_session,
)

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
    # These cases describe a controller, so the xdist worker marker this very
    # test may be running under is cleared too.
    names: dict[str, str | None] = dict.fromkeys((*_SEAT_NAMES, "PYTEST_XDIST_WORKER"))
    names.update(values)
    return names


def test_the_light_harness_names_are_the_ones_the_settings_read() -> None:
    """The import-light spellings must never drift from the schema."""
    assert (
        env_name(TestSessionSettings, "completion_endpoint")
        == harness_names.COMPLETION_ENDPOINT_ENV
    )
    assert (
        env_name(TestSessionSettings, "completion_owner_pid")
        == harness_names.COMPLETION_OWNER_PID_ENV
    )
    assert env_name(TestSessionSettings, "cpu_budget") == harness_names.CPU_BUDGET_ENV


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
    environment = inherited_environment(
        {
            "PYTEST_XDIST_WORKER": "gw0",
            env_name(TestSessionSettings, "session_root"): str(tmp_path / "p"),
            env_name(TestSessionSettings, "session_pid"): "1",
        }
    )

    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "nested")],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    assert Path(completed.stdout.strip()).is_relative_to(tmp_path / "nested")


_OPERATOR_PORT = "17742"
_DEFAULT_PORT = 18000

_SEATED_PROBE = """
import os
import sys
from pathlib import Path

from vaultspec_a2a.control.settings_base import ENV_FILE_ENV
from vaultspec_a2a.testing.session_root import seat_test_session

seat_test_session(Path(sys.argv[1]))

from vaultspec_a2a.control.config import Settings

print(os.environ.get(ENV_FILE_ENV, "<removed>"))
print(Settings().port)
"""


def _seated_session(rootdir: Path, named: str) -> subprocess.CompletedProcess[str]:
    """Seat a session in a real child process that inherits *named* as its env file."""
    probe = rootdir / "probe.py"
    probe.write_text(_SEATED_PROBE, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(probe), str(rootdir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
        env=inherited_environment(
            {
                **dict.fromkeys(
                    name for name in os.environ if name.startswith("VAULTSPEC_A2A_")
                ),
                "PYTHONIOENCODING": "utf-8",
                env_name(InfraConfig, "project_root"): str(rootdir),
                "VAULTSPEC_A2A_ENV_FILE": named,
            }
        ),
    )


def test_a_session_ignores_an_operator_settings_file_it_inherited(
    tmp_path: Path,
) -> None:
    """A developer's exported settings file has no say in what a test reads.

    The operator reference tells developers to export it, so a session started
    from such a shell would otherwise take that file's ports, database and
    timeouts for the whole run - values no test declared and none can see.
    """
    operator = tmp_path / "operator.env"
    operator.write_text(f"VAULTSPEC_A2A_PORT={_OPERATOR_PORT}\n", encoding="utf-8")

    seated = _seated_session(tmp_path, str(operator))

    assert seated.returncode == 0, seated.stderr
    named, port = seated.stdout.split()
    assert named == "<removed>"
    assert int(port) == _DEFAULT_PORT


def test_a_session_survives_an_operator_settings_file_that_is_not_there(
    tmp_path: Path,
) -> None:
    """A stale export breaks a developer's run, not their whole test session."""
    seated = _seated_session(tmp_path, str(tmp_path / "absent.env"))

    assert seated.returncode == 0, seated.stderr
    assert seated.stdout.split()[0] == "<removed>"


def _aged_dir(root: Path, name: str, *, age_seconds: float) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session-summary.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(directory, (stamp, stamp))
    return directory


def test_stale_directories_are_bounded_and_evict_oldest_first(
    tmp_path: Path,
) -> None:
    """Recent post-mortems survive; older runs are reclaimed."""
    kept_newest = 5
    root = tmp_path / "service-tests"
    root.mkdir()

    created = [
        _aged_dir(root, f"run-{index:03d}", age_seconds=1000 - index)
        for index in range(kept_newest + 3)
    ]

    removed = prune_stale_dirs(root, kept_newest=kept_newest)

    surviving = sorted(entry.name for entry in root.iterdir())
    assert len(surviving) == kept_newest
    assert len(removed) == 3
    # The newest have the largest index because age decreases with index.
    assert created[-1].name in surviving
