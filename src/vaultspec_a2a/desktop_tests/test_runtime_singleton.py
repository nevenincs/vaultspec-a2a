"""Certify two real desktop gateways cannot own or overwrite one app home.

Each certification spawns real child interpreters that run the production desktop
ownership surface: acquire the runtime singleton over an explicit application
home (the serve path takes it before the listener binds), then publish the
versioned discovery record. A second gateway against the same home must fail
loud at acquisition without corrupting the first's discovery record; after the
first is really killed, an owner-matching restart succeeds through stale
classification.

Ownership is certified through the discovery/singleton records — never a launch
handle — because desktop-serve re-execs a fresh interpreter whose launcher pid
differs from the real gateway process. No mock, monkeypatch, stub, skip, or
expected failure is used; children are always torn down in a ``finally``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from vaultspec_a2a.lifecycle.discovery import (
    DesktopDiscoveryState,
    classify_desktop_discovery,
    read_desktop_discovery,
    service_json_path,
)
from vaultspec_a2a.lifecycle.singleton import (
    SingletonState,
    classify_app_home,
)

if TYPE_CHECKING:
    from pathlib import Path

# A real "gateway": take the runtime singleton first (as the serve path does
# before bind), then publish the versioned discovery record, then hold. On an
# acquisition conflict it records the classification and exits non-zero without
# ever touching discovery — proving the ordering protects a resident's record.
_GATEWAY = """
import sys, os, json
from pathlib import Path
from vaultspec_a2a.lifecycle.singleton import acquire_singleton, SingletonConflictError
from vaultspec_a2a.lifecycle.discovery import write_desktop_discovery, service_json_path
app_home, owner, port, ready, stop, outcome = (
    Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]),
    Path(sys.argv[4]), Path(sys.argv[5]), Path(sys.argv[6]),
)
try:
    singleton = acquire_singleton(app_home, owner=owner)
except SingletonConflictError as exc:
    outcome.write_text(json.dumps({"result": "conflict", "state": exc.state.value}))
    sys.exit(3)
record = write_desktop_discovery(
    service_json_path(app_home), generation="gen-1", port=port, owner=owner
)
ready.write_text(json.dumps({"pid": os.getpid(), "port": record.port}))
import time as _t
try:
    while not stop.exists():
        _t.sleep(0.05)
finally:
    singleton.release()
"""


def _spawn_gateway(
    tmp_path: Path, app_home: Path, owner: str, port: int, tag: str
) -> dict:
    """Spawn a gateway child and return handles plus its signal files."""
    ready = tmp_path / f"{tag}.ready"
    stop = tmp_path / f"{tag}.stop"
    outcome = tmp_path / f"{tag}.outcome"
    proc = subprocess.Popen(
        [
            sys.executable, "-c", _GATEWAY, str(app_home), owner, str(port),
            str(ready), str(stop), str(outcome),
        ],
        env=os.environ.copy(),
    )
    return {"proc": proc, "ready": ready, "stop": stop, "outcome": outcome}


def _await(path: Path, *, timeout: float = 25.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text()
            if text:
                return text
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _stop(handle: dict, *, timeout: float = 25.0) -> int:
    handle["stop"].touch()
    try:
        return handle["proc"].wait(timeout=timeout)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive teardown
        handle["proc"].kill()
        return handle["proc"].wait(timeout=timeout)


def test_second_gateway_cannot_own_or_overwrite_the_home(tmp_path: Path) -> None:
    """A second gateway fails loud and leaves the first's discovery record intact."""
    app_home = tmp_path / "app"
    first = _spawn_gateway(tmp_path, app_home, "owner-a", 8300, "first")
    try:
        first_ready = json.loads(_await(first["ready"]))
        # Certify via the published record's process identity, not the launch pid.
        record_before = read_desktop_discovery(service_json_path(app_home))
        assert record_before is not None
        assert record_before.pid == first_ready["pid"]
        assert record_before.port == 8300
        assert record_before.owner == "owner-a"
        assert classify_app_home(app_home, owner="owner-a")[0] is SingletonState.HELD

        # A second gateway on the same home must fail loud at acquisition.
        second = _spawn_gateway(tmp_path, app_home, "owner-b", 8301, "second")
        second_code = second["proc"].wait(timeout=25)
        assert second_code == 3
        outcome = json.loads(second["outcome"].read_text())
        assert outcome["result"] == "conflict"

        # The first gateway's record is untouched: the failed contender never
        # reached discovery publication (singleton is taken before publish).
        record_after = read_desktop_discovery(service_json_path(app_home))
        assert record_after == record_before
    finally:
        _stop(first)


def test_owner_restart_after_real_kill_reclaims_via_stale(tmp_path: Path) -> None:
    """After the owner is killed, a same-owner restart reclaims through STALE."""
    app_home = tmp_path / "app"
    first = _spawn_gateway(tmp_path, app_home, "owner-a", 8302, "first")
    first_pid = 0
    try:
        first_pid = json.loads(_await(first["ready"]))["pid"]
    finally:
        first["proc"].terminate()
        first["proc"].wait(timeout=25)

    # The killed gateway's runtime singleton is now stale (recorded process dead).
    state, record = classify_app_home(app_home, owner="owner-a")
    assert state is SingletonState.STALE
    assert record is not None and record.pid == first_pid

    # A same-owner restart takes over and republishes its own discovery record.
    restart = _spawn_gateway(tmp_path, app_home, "owner-a", 8303, "restart")
    try:
        restart_ready = json.loads(_await(restart["ready"]))
        assert restart_ready["pid"] != first_pid
        new_state, new_record = classify_desktop_discovery(service_json_path(app_home))
        assert new_state is DesktopDiscoveryState.FRESH
        assert new_record is not None
        assert new_record.pid == restart_ready["pid"]
        assert new_record.port == 8303
        assert classify_app_home(app_home, owner="owner-a")[0] is SingletonState.HELD
    finally:
        _stop(restart)
