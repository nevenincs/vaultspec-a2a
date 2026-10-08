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
from typing import TYPE_CHECKING, TypedDict, cast

from ..lifecycle.discovery import (
    DiscoveryState,
    classify_desktop_discovery,
    service_json_path,
)
from ..lifecycle.singleton import (
    SingletonState,
    classify_app_home,
)
from ..testing import SignalledChild, free_port, spawn_signalled
from ..utils import reap_contained

if TYPE_CHECKING:
    from pathlib import Path


class _ReadyPayload(TypedDict):
    """Payload a gateway child writes to its ``ready`` signal file."""

    pid: int
    port: int


# A real "gateway": take the runtime singleton first (as the serve path does
# before bind), then publish the versioned discovery record, then hold. On an
# acquisition conflict it records the classification and exits non-zero without
# ever touching discovery — proving the ordering protects a resident's record.
_GATEWAY = """
import sys, os, json
from pathlib import Path
from vaultspec_a2a.lifecycle.singleton import acquire_singleton, SingletonConflictError
from vaultspec_a2a.lifecycle.discovery import write_desktop_discovery, service_json_path
app_home, owner, port, outcome, ready, stop = (
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
) -> tuple[SignalledChild, Path]:
    """Spawn a gateway child; return it and the file it records a conflict in."""
    outcome = tmp_path / f"{tag}.outcome"
    child = spawn_signalled(
        _GATEWAY,
        str(app_home),
        owner,
        str(port),
        str(outcome),
        signal_dir=tmp_path,
        tag=tag,
    )
    return child, outcome


def test_second_gateway_cannot_own_or_overwrite_the_home(tmp_path: Path) -> None:
    """A second gateway fails loud and leaves the first's discovery record intact."""
    app_home = tmp_path / "app"
    port = free_port()
    first, _first_outcome = _spawn_gateway(tmp_path, app_home, "owner-a", port, "first")
    try:
        first_ready = cast("_ReadyPayload", json.loads(first.payload()))
        # Certify via the published record's process identity, not the launch pid.
        record_before = classify_desktop_discovery(service_json_path(app_home))[1]
        assert record_before is not None
        assert record_before.pid == first_ready["pid"]
        assert record_before.port == port
        assert record_before.owner == "owner-a"
        assert classify_app_home(app_home, owner="owner-a")[0] is SingletonState.HELD

        # A second gateway on the same home must fail loud at acquisition.
        second, second_outcome = _spawn_gateway(
            tmp_path, app_home, "owner-b", free_port(), "second"
        )
        second_code = second.request_stop()
        assert second_code == 3
        outcome = cast("dict[str, str]", json.loads(second_outcome.read_text()))
        assert outcome["result"] == "conflict"

        # The first gateway's record is untouched: the failed contender never
        # reached discovery publication (singleton is taken before publish).
        record_after = classify_desktop_discovery(service_json_path(app_home))[1]
        assert record_after == record_before
    finally:
        first.request_stop()


def test_owner_restart_after_real_kill_reclaims_via_stale(tmp_path: Path) -> None:
    """After the owner is killed, a same-owner restart reclaims through STALE."""
    app_home = tmp_path / "app"
    first, _first_outcome = _spawn_gateway(
        tmp_path, app_home, "owner-a", free_port(), "first"
    )
    first_pid = 0
    try:
        first_pid = cast("_ReadyPayload", json.loads(first.payload()))["pid"]
    finally:
        # A stop request would release the singleton cleanly; the kill is what
        # leaves it stale, and the containment reaps whatever else the child ran.
        reap_contained(first.process, first.containment)

    # The killed gateway's runtime singleton is now stale (recorded process dead).
    state, record = classify_app_home(app_home, owner="owner-a")
    assert state is SingletonState.STALE
    assert record is not None and record.pid == first_pid

    # A same-owner restart takes over and republishes its own discovery record.
    restart_port = free_port()
    restart, _restart_outcome = _spawn_gateway(
        tmp_path, app_home, "owner-a", restart_port, "restart"
    )
    try:
        restart_ready = cast("_ReadyPayload", json.loads(restart.payload()))
        assert restart_ready["pid"] != first_pid
        new_state, new_record = classify_desktop_discovery(service_json_path(app_home))
        assert new_state is DiscoveryState.FRESH
        assert new_record is not None
        assert new_record.pid == restart_ready["pid"]
        assert new_record.port == restart_port
        assert classify_app_home(app_home, owner="owner-a")[0] is SingletonState.HELD
    finally:
        restart.request_stop()
