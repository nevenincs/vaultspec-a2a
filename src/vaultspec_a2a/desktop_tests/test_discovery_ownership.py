"""Certify desktop discovery ownership: attach, stale recovery, live conflict.

Real child interpreters stand up a live desktop resident (runtime singleton plus
published versioned discovery). Against it these tests prove the P07 discovery
ownership state machine end to end:

- A foreign contender can read and validate a live compatible resident's
  discovery record and follows its named, owner-restricted attach-credential
  reference, yet can never take lifecycle ownership — attachment is not
  ownership.
- A live incompatible or malformed resident is an immutable conflict: the
  contender neither attaches nor claims the home.
- Stale discovery (the recorded gateway proven dead) is quarantined only by the
  matching owner; a foreign owner is refused.

Full attach-credential authentication lands in W03.P08; this certifies the
discovery-validation and conflict/quarantine machine that gates it. No mock,
monkeypatch, stub, skip, or expected failure is used; children are always torn
down in a ``finally``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.lifecycle.discovery import (
    DesktopDiscoveryState,
    classify_desktop_discovery,
    desktop_record_process_is_live,
    read_desktop_discovery,
    service_json_path,
)
from vaultspec_a2a.lifecycle.singleton import (
    SingletonConflictError,
    SingletonState,
    acquire_singleton,
    classify_app_home,
)

if TYPE_CHECKING:
    from pathlib import Path

# A real resident: take the singleton, write an owner-restricted attach
# credential file, publish the versioned discovery record naming it by path
# (never by value), then hold. Protocol range is parameterised so a test can
# stand up an incompatible resident.
_RESIDENT = """
import sys, os, json
from pathlib import Path
from vaultspec_a2a.lifecycle.singleton import acquire_singleton
from vaultspec_a2a.lifecycle.discovery import write_desktop_discovery, service_json_path
app_home, owner, port, pmin, pmax, ready, stop = (
    Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), int(sys.argv[4]),
    int(sys.argv[5]), Path(sys.argv[6]), Path(sys.argv[7]),
)
singleton = acquire_singleton(app_home, owner=owner)
creds = app_home / "credentials"
creds.mkdir(parents=True, exist_ok=True)
credential_file = creds / "attach-control.cred"
credential_file.write_text("attach-bearer-secret", encoding="utf-8")
record = write_desktop_discovery(
    service_json_path(app_home), generation="gen-1", port=port, owner=owner,
    credential_reference=str(credential_file), protocol_min=pmin, protocol_max=pmax,
)
ready.write_text(json.dumps({"pid": os.getpid(), "port": record.port}))
import time as _t
try:
    while not stop.exists():
        _t.sleep(0.05)
finally:
    singleton.release()
"""


def _spawn_resident(
    tmp_path: Path,
    app_home: Path,
    owner: str,
    port: int,
    tag: str,
    *,
    protocol: tuple[int, int] = (1, 1),
) -> dict:
    ready = tmp_path / f"{tag}.ready"
    stop = tmp_path / f"{tag}.stop"
    proc = subprocess.Popen(
        [
            sys.executable, "-c", _RESIDENT, str(app_home), owner, str(port),
            str(protocol[0]), str(protocol[1]), str(ready), str(stop),
        ],
        env=os.environ.copy(),
    )
    return {"proc": proc, "ready": ready, "stop": stop}


def _await(path: Path, *, timeout: float = 25.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _stop(handle: dict, *, timeout: float = 25.0) -> None:
    handle["stop"].touch()
    try:
        handle["proc"].wait(timeout=timeout)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive teardown
        handle["proc"].kill()
        handle["proc"].wait(timeout=timeout)


def test_foreign_contender_validates_but_never_owns(tmp_path: Path) -> None:
    """A contender validates a live compatible resident yet cannot take ownership."""
    app_home = tmp_path / "app"
    resident = _spawn_resident(tmp_path, app_home, "owner-a", 8400, "res")
    try:
        _await(resident["ready"])
        state, record = classify_desktop_discovery(service_json_path(app_home))
        assert state is DesktopDiscoveryState.FRESH
        assert record is not None
        # Validate: process live, protocol compatible, attach reference named.
        assert desktop_record_process_is_live(record) is True
        assert record.supports_protocol(1) is True
        assert record.credential_reference is not None
        assert os.path.isfile(record.credential_reference)

        # Attachment is not ownership: a foreign owner cannot take the singleton.
        assert classify_app_home(app_home, owner="owner-b")[0] is SingletonState.FOREIGN
        with pytest.raises(SingletonConflictError) as conflict:
            acquire_singleton(app_home, owner="owner-b")
        assert conflict.value.state is SingletonState.FOREIGN
    finally:
        _stop(resident)


def test_live_incompatible_resident_is_immutable_conflict(tmp_path: Path) -> None:
    """An incompatible protocol resident is refused for attach and for ownership."""
    app_home = tmp_path / "app"
    resident = _spawn_resident(
        tmp_path, app_home, "owner-a", 8401, "res", protocol=(2, 2)
    )
    try:
        _await(resident["ready"])
        record = read_desktop_discovery(service_json_path(app_home))
        assert record is not None
        # A protocol-1 contender is incompatible: it must not attach.
        assert record.supports_protocol(1) is False
        # And it cannot claim the home either — live foreign resident.
        with pytest.raises(SingletonConflictError) as conflict:
            acquire_singleton(app_home, owner="owner-b")
        assert conflict.value.state is SingletonState.FOREIGN
    finally:
        _stop(resident)


def test_live_malformed_discovery_is_immutable_conflict(tmp_path: Path) -> None:
    """A live resident with a corrupted discovery record is an immutable conflict."""
    app_home = tmp_path / "app"
    resident = _spawn_resident(tmp_path, app_home, "owner-a", 8402, "res")
    try:
        _await(resident["ready"])
        # Corrupt the published record while the resident is still live.
        service_json_path(app_home).write_text("{ not json", encoding="utf-8")
        assert (
            classify_desktop_discovery(service_json_path(app_home))[0]
            is DesktopDiscoveryState.MALFORMED
        )
        # The singleton still proves a live resident: no takeover.
        with pytest.raises(SingletonConflictError) as conflict:
            acquire_singleton(app_home, owner="owner-b")
        assert conflict.value.state is SingletonState.FOREIGN
    finally:
        _stop(resident)


def test_stale_discovery_quarantined_only_by_owner(tmp_path: Path) -> None:
    """After the resident dies, only the matching owner may reclaim the home."""
    app_home = tmp_path / "app"
    resident = _spawn_resident(tmp_path, app_home, "owner-a", 8403, "res")
    dead_pid = 0
    try:
        dead_pid = json.loads(_await(resident["ready"]))["pid"]
    finally:
        resident["proc"].terminate()
        resident["proc"].wait(timeout=25)

    # The heartbeat is still recent, so the filesystem-only classifier reads
    # FRESH — but the recorded process is provably dead, which the ownership
    # layer detects.
    record = read_desktop_discovery(service_json_path(app_home))
    assert record is not None and record.pid == dead_pid
    assert desktop_record_process_is_live(record) is False
    assert classify_app_home(app_home, owner="owner-a")[0] is SingletonState.STALE

    # A foreign owner may not quarantine another owner's stale home.
    with pytest.raises(SingletonConflictError) as foreign:
        acquire_singleton(app_home, owner="owner-b")
    assert foreign.value.state is SingletonState.STALE

    # The matching owner reclaims through stale takeover.
    singleton = acquire_singleton(app_home, owner="owner-a")
    try:
        assert singleton.record.pid == os.getpid()
        assert classify_app_home(app_home, owner="owner-a")[0] is SingletonState.HELD
    finally:
        singleton.release()
