"""Real-behavior tests for the service-management verbs.

``setup`` runs the real Alembic/checkpointer initialisation against scratch
stores; ``status``/``stop`` are exercised against absent, dead, and live
residents; the start→status→stop→restart cycle boots the real gateway serve
path as a detached subprocess on a scratch application home and free ports.
No mocks, no fakes: every verdict asserted here is observed from a real
process, socket, or SQLite file.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import socket
import subprocess
import sys
from typing import TYPE_CHECKING, TypedDict

import pytest

from ...testing import (
    DEFAULT_OWNERSHIP_CAPABILITY,
    JsonReplyHandler,
    free_port,
    run_cli,
    serve_handler,
    settings_override,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

from ...desktop._platform_acl import harden_credential_path
from ...desktop.credentials import OWNERSHIP_CAPABILITY_NAME
from ...desktop.profile import derive_state_paths
from ...lifecycle.discovery import (
    read_resident_service,
    service_json_path,
    write_service_json,
)
from ...utils._process_tree import pid_is_live, wait_pid_gone
from ..service import (
    ServiceVerbError,
    StartOptions,
    restart_service,
    service_status,
    setup_service,
    start_service,
    stop_service,
)

# A well-formed handoff credential, so the record resolves a real attach bearer
# the way a live resident's does.
_SERVICE_TOKEN = "stop-verb-service-token-0123456789"


class _ReceivedRequest(TypedDict):
    """One request the recorded endpoint's occupant actually received."""

    method: str
    path: str
    authorization: str | None
    capability: str | None


@contextlib.contextmanager
def _recording_occupant() -> Generator[tuple[int, list[_ReceivedRequest]]]:
    """A real loopback listener that logs every request, including its headers.

    The log is what separates "no credential was sent" from "no request was
    sent", and the stop verb owes a foreign occupant the stronger of the two.
    """
    from ...api.dependencies import LIFECYCLE_CAPABILITY_HEADER

    received: list[_ReceivedRequest] = []

    class _Handler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
        def _record(self, method: str) -> None:
            received.append(
                {
                    "method": method,
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "capability": self.headers.get(LIFECYCLE_CAPABILITY_HEADER),
                }
            )

        def do_GET(self) -> None:
            self._record("GET")
            self._reply(200, {"service": "gateway", "ready": True})

        def do_POST(self) -> None:
            self._record("POST")
            self._reply_empty(202)

    with serve_handler(_Handler) as port:
        yield port, received


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
    # Mint a genuinely-dead pid portably: the interpreter that runs the suite
    # exists on every platform, unlike the Windows-only ``cmd`` shell.
    dead = subprocess.Popen([sys.executable, "-c", ""])
    dead.wait()
    write_service_json(
        service_json_path(home),
        port=free_port(),
        pid=dead.pid,
        allow_tokenless=True,
    )
    status = service_status(home)
    assert status.state == "stopped"
    assert status.pid == dead.pid


def test_stop_leaves_a_stranger_that_inherited_the_recorded_pid_alone(
    tmp_path: Path,
) -> None:
    """A reused pid is not the resident the record names, so it is not felled.

    A crashed resident leaves its record behind, and the operating system is
    free to hand that pid to anything. The record then names a live pid that was
    never this service: pid-liveness alone reads it as the resident and fells
    whatever now holds it - an unrelated build, editor, or another stack's
    service - because the endpoint is free, which is the one claim that licenses
    the kill outright.

    The start fingerprint is what tells the two apart. The record here carries
    the fingerprint of THIS process, a real identity belonging to a real but
    different process, exactly as a pid-reuse record does.
    """
    from ...lifecycle.singleton import current_process_fingerprint

    home = tmp_path / "home"
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        write_service_json(
            service_json_path(home),
            port=free_port(),
            pid=stranger.pid,
            start_fingerprint=current_process_fingerprint(),
            allow_tokenless=True,
        )

        with settings_override(a2a_home=home):
            status = stop_service(home)

        assert pid_is_live(stranger.pid) is True, (
            "stop felled the stranger that inherited the recorded pid"
        )
        assert status.state == "stopped"
    finally:
        stranger.kill()
        stranger.wait(timeout=10)


def test_stop_fells_the_recorded_resident_whose_fingerprint_still_matches(
    tmp_path: Path,
) -> None:
    """The fingerprint check must not disarm the stop verb it guards.

    Same shape as the reuse case above and the same free endpoint, differing
    only in the one fact under test: the record names the process that is
    actually running under that pid. That record is addressable, so the recorded
    tree is felled.
    """
    home = tmp_path / "home"
    resident = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        write_service_json(
            service_json_path(home),
            port=free_port(),
            pid=resident.pid,
            allow_tokenless=True,
        )
        recorded = read_resident_service(home)[1]
        assert recorded is not None
        assert recorded.start_fingerprint is not None, (
            "the record published no start fingerprint to match against"
        )

        with settings_override(a2a_home=home):
            stop_service(home)

        wait_pid_gone(resident.pid, timeout=10)
        assert pid_is_live(resident.pid) is False
    finally:
        if resident.poll() is None:
            resident.kill()
        resident.wait(timeout=10)


def test_stop_sends_nothing_to_an_endpoint_the_recorded_pid_does_not_own(
    tmp_path: Path,
) -> None:
    """A recorded pid that does not hold the listener is a conflict, not a target.

    The record names a live process and a real loopback endpoint, but a DIFFERENT
    process holds that endpoint - the shape a pid-reused record, a crashed
    resident whose port was taken, or an outright squatter produces. The stop
    verb must confirm the recorded process owns the listener BEFORE it presents
    the attach bearer or the receipt-bound lifecycle capability, so the occupant
    receives no request at all; and because ownership was never established, the
    recorded process is not felled either.
    """
    home = tmp_path / "home"
    state = derive_state_paths(home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    capability = state.credentials_dir / OWNERSHIP_CAPABILITY_NAME
    capability.write_text(DEFAULT_OWNERSHIP_CAPABILITY, encoding="utf-8")
    harden_credential_path(capability)

    # Live, and holding nothing: the record's pid must not be read as the owner
    # of a listener merely because it is alive.
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        with _recording_occupant() as (port, received):
            write_service_json(
                service_json_path(home),
                port=port,
                pid=stranger.pid,
                service_token=_SERVICE_TOKEN,
            )
            with settings_override(a2a_home=home), pytest.raises(ServiceVerbError):
                stop_service(home)
            seen_by_the_occupant = list(received)
        assert seen_by_the_occupant == []
        assert pid_is_live(stranger.pid) is True
    finally:
        stranger.kill()
        stranger.wait(timeout=10)


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
    port = free_port()

    started = start_service(
        home, StartOptions(port=port, log_path=str(tmp_path / "gateway.log"))
    )
    assert started.state == "running", started
    assert started.port == port
    assert started.pid is not None and pid_is_live(started.pid)

    observed = service_status(home)
    assert observed.state == "running"
    assert observed.pid == started.pid

    restarted = restart_service(
        home, StartOptions(port=port, log_path=str(tmp_path / "gateway.log"))
    )
    assert restarted.state == "running", restarted
    assert restarted.pid is not None and pid_is_live(restarted.pid)
    assert restarted.pid != started.pid
    assert not pid_is_live(started.pid)

    stopped = stop_service(home)
    assert stopped.state == "stopped", stopped
    assert restarted.pid is not None
    assert wait_pid_gone(restarted.pid, timeout=10)


@pytest.mark.timeout(120)
def test_cli_status_command_shapes_json_and_exit_codes(tmp_path: Path) -> None:
    """The status verb emits bounded JSON and carries the verdict in its exit."""
    home = tmp_path / "home"
    result = run_cli("status", "--app-home", str(home))
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
                StartOptions(
                    port=held_port,
                    log_path=str(tmp_path / "gateway.log"),
                    # The occupied port makes readiness impossible. Keep this a
                    # real detached-process cleanup proof without idling for the
                    # production startup budget.
                    ready_timeout=3.0,
                ),
            )
        _, info = read_resident_service(home)
        assert info is None or info.pid is None or not pid_is_live(info.pid)
    finally:
        holder.close()
