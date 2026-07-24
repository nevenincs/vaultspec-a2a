"""Real-behavior tests for the service-management verbs.

``setup`` runs the real Alembic/checkpointer initialisation against scratch
stores; ``status``/``stop`` are exercised against absent, dead, and live
residents; the start→status→stop→restart cycle boots the real gateway serve
path as a detached subprocess on a scratch application home and free ports.
No mocks, no fakes: every verdict asserted here is observed from a real
process, socket, or SQLite file.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ...desktop.profile import derive_state_paths
from ...lifecycle.discovery import (
    is_pid_alive,
    read_resident_service,
    service_json_path,
    write_service_json,
)
from ..service import (
    restart_service,
    service_status,
    setup_service,
    start_service,
    stop_service,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_status_on_empty_home_reports_stopped(tmp_path: Path) -> None:
    status = service_status(tmp_path / "home")
    assert status.state == "stopped"
    assert status.pid is None
    assert not status.healthy


def test_stop_on_empty_home_is_idempotent(tmp_path: Path) -> None:
    """Stopping a home with no resident succeeds and reports the stopped state."""
    status = stop_service(tmp_path / "home")
    assert status.state == "stopped"


def test_status_with_dead_recorded_pid_reports_stopped(tmp_path: Path) -> None:
    """A record whose pid is gone is a stopped service, not a live one."""
    home = tmp_path / "home"
    home.mkdir()
    dead = subprocess.Popen(["cmd", "/c", "exit 0"])
    dead.wait()
    write_service_json(
        service_json_path(home),
        port=_free_port(),
        pid=dead.pid,
        allow_tokenless=True,
    )
    status = service_status(home)
    assert status.state == "stopped"
    assert status.pid == dead.pid


def test_setup_initialises_fresh_stores_and_is_idempotent(tmp_path: Path) -> None:
    """Setup brings absent stores to the packaged head, then reports as-is.

    First run: real Alembic upgrade plus checkpointer schema against scratch
    SQLite files. Second run: the initialised primary store makes setup report
    ``already-initialized`` instead of mutating or failing.
    """
    home = tmp_path / "home"
    first = setup_service(home)
    assert first["status"] == "succeeded", first
    state = derive_state_paths(home)
    assert state.database_path.is_file()
    assert state.checkpoint_path.is_file()
    stores = {store["store"]: store["status"] for store in first["stores"]}
    assert stores == {
        "primary": "migrated",
        "checkpoint": "initialized",
        "sdd": "backfilled",
    }

    second = setup_service(home)
    assert second["status"] == "already-initialized", second


def test_migrate_upgrades_setup_home_and_asserts_fail_closed(tmp_path: Path) -> None:
    """Migrate reaches the packaged head on an initialised home; assertions refuse.

    The dashboard-spawn contract: after setup, migrate is an idempotent
    upgrade-to-head; a base or head assertion that does not match the real
    store or package fails closed at the precondition stage.
    """
    from ...desktop.migration import package_migration_range
    from ..service import migrate_service

    home = tmp_path / "home"
    assert setup_service(home)["status"] == "succeeded"
    packaged = package_migration_range()

    upgraded = migrate_service(
        home, expect_from=packaged.head, expect_head=packaged.head
    )
    assert upgraded["status"] == "succeeded", upgraded
    stores = {store["store"]: store for store in upgraded["stores"]}
    assert stores["primary"]["from_revision"] == packaged.head
    assert stores["primary"]["to_revision"] == packaged.head

    refused = migrate_service(home, expect_head="9999_future")
    assert refused["status"] == "failed"
    assert refused["failed_stage"] == "precondition"
    assert refused["error_class"] == "HeadMismatchError"


@pytest.mark.timeout(120)
def test_start_status_stop_restart_cycle_on_scratch_home(tmp_path: Path) -> None:
    """The full management cycle against a real detached gateway.

    start publishes a ready resident on the scratch home (fresh discovery
    record, live pid, answering health endpoint); status agrees; restart
    replaces the generation (new pid, still ready); stop confirms the pid is
    gone and reports stopped. This is the dashboard's contract end to end.
    """
    home = tmp_path / "home"
    port = _free_port()

    started = start_service(home, port=port, log_path=str(tmp_path / "gateway.log"))
    assert started.state == "running", started
    assert started.port == port
    assert started.pid is not None and is_pid_alive(started.pid)

    observed = service_status(home)
    assert observed.state == "running"
    assert observed.pid == started.pid

    restarted = restart_service(home, port=port, log_path=str(tmp_path / "gateway.log"))
    assert restarted.state == "running", restarted
    assert restarted.pid is not None and is_pid_alive(restarted.pid)
    assert restarted.pid != started.pid
    assert not is_pid_alive(started.pid)

    stopped = stop_service(home)
    assert stopped.state == "stopped", stopped
    assert restarted.pid is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and is_pid_alive(restarted.pid):
        time.sleep(0.1)
    assert not is_pid_alive(restarted.pid)


@pytest.mark.timeout(120)
def test_cli_status_command_shapes_json_and_exit_codes(tmp_path: Path) -> None:
    """The status verb emits bounded JSON and carries the verdict in its exit."""
    from ...utils.runtime_exec import self_command

    home = tmp_path / "home"
    result = subprocess.run(
        [*self_command(), "status", "--app-home", str(home)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["state"] == "stopped"
    assert payload["healthy"] is False


def test_start_failure_fells_the_spawn_and_raises(tmp_path: Path) -> None:
    """A gateway that can never become ready is felled, not leaked.

    Forcing the child onto a port another socket already holds makes the serve
    boot fail; the verb must raise loudly and leave no surviving process or
    published record behind.
    """
    from ..service import ServiceVerbError

    home = tmp_path / "home"
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    held_port = holder.getsockname()[1]
    try:
        with pytest.raises(ServiceVerbError):
            start_service(
                home,
                port=held_port,
                log_path=str(tmp_path / "gateway.log"),
                ready_timeout=25.0,
            )
        _, info = read_resident_service(home)
        assert info is None or not is_pid_alive(info.pid)
    finally:
        holder.close()
