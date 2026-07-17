"""File-per-process registry core.

Real filesystem, real process pids, and real loopback socket binds - no mocks.
The registry home is an isolated ``tmp_path`` per test, the live pid is this test
process (``os.getpid()``), and a genuinely dead pid comes from a spawned process
that has already exited, so liveness and ownership verdicts are exercised against
the real OS, not a stub.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import Any

import pytest

from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registry import (
    ProcRecord,
    RegistryOwnershipError,
    StalenessState,
    _port_is_free,
    allocate_port,
    classify_record,
    commit_reservation,
    list_records,
    now_ms,
    read_record,
    record_path,
    refresh_last_seen,
    release_reservation,
    remove_record_if_owned,
    reserve_port,
    write_record,
)


def _dead_pid() -> int:
    """Spawn a trivial process, wait for it to exit, and return its now-dead pid."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _record(**overrides: Any) -> ProcRecord:
    base: dict[str, Any] = {
        "name": "alpha",
        "role": "gateway-dev",
        "pid": os.getpid(),
        "port": 18100,
        "owner": "session-a",
        "started_at_ms": now_ms(),
        "last_seen_ms": now_ms(),
    }
    base.update(overrides)
    return ProcRecord(**base)


def test_write_then_read_roundtrips_at_the_named_path(tmp_path) -> None:
    record = _record(command=["vaultspec-a2a", "serve", "--port", "18100"])
    path = write_record(record, home=tmp_path)

    assert path == record_path("gateway-dev", "alpha", home=tmp_path)
    assert path.name == "gateway-dev-alpha.json"
    back = read_record(path)
    assert back == record


def test_build_repo_roundtrips_through_the_record_schema(tmp_path) -> None:
    # A distinct build tree captured in the machine-global record (never in the
    # committed procs.toml) must survive write -> read intact.
    record = _record(build_repo="Z:/dashboard/main/engine")
    path = write_record(record, home=tmp_path)
    back = read_record(path)
    assert back == record
    assert back is not None
    assert back.build_repo == "Z:/dashboard/main/engine"


def test_engine_service_json_roundtrips_through_the_record_schema(tmp_path) -> None:
    # The recorded engine-discovery path (machine-specific, never in procs.toml) must
    # survive write -> read so resume/rerun can re-inject it.
    record = _record(engine_service_json="C:/dashboard/main/engine-service.json")
    path = write_record(record, home=tmp_path)
    back = read_record(path)
    assert back == record
    assert back is not None
    assert back.engine_service_json == "C:/dashboard/main/engine-service.json"


def test_list_enumerates_valid_and_skips_malformed(tmp_path) -> None:
    write_record(_record(name="alpha", port=18100), home=tmp_path)
    write_record(_record(name="beta", port=18101), home=tmp_path)
    # A malformed sibling file must not break enumeration.
    (tmp_path / "gateway-dev-broken.json").write_text("{not json", encoding="utf-8")

    names = {r.name for r in list_records(tmp_path)}
    assert names == {"alpha", "beta"}


def test_write_refuses_to_clobber_a_live_record_of_another_owner(tmp_path) -> None:
    # A live record (this process's pid) owned by session-a.
    write_record(_record(owner="session-a", pid=os.getpid()), home=tmp_path)

    # session-b cannot overwrite it while its process is alive.
    with pytest.raises(RegistryOwnershipError, match="held by a live process"):
        write_record(_record(owner="session-b", pid=os.getpid()), home=tmp_path)


def test_write_reclaims_a_dead_record_of_another_owner(tmp_path) -> None:
    write_record(_record(owner="session-a", pid=_dead_pid()), home=tmp_path)

    # The prior owner's process is dead, so the record is freely reclaimable.
    reclaimed = _record(owner="session-b", pid=os.getpid())
    write_record(reclaimed, home=tmp_path)
    assert read_record(record_path("gateway-dev", "alpha", home=tmp_path)) == reclaimed


def test_remove_if_owned_respects_a_live_foreign_owner(tmp_path) -> None:
    write_record(_record(owner="session-a", pid=os.getpid()), home=tmp_path)

    # A different owner cannot remove a live record ...
    assert (
        remove_record_if_owned("gateway-dev", "alpha", "session-b", home=tmp_path)
        is False
    )
    # ... but the holder can.
    assert (
        remove_record_if_owned("gateway-dev", "alpha", "session-a", home=tmp_path)
        is True
    )
    assert read_record(record_path("gateway-dev", "alpha", home=tmp_path)) is None


def _role(band: PortBand, *, heartbeat: bool, staleness_ms: int = 120000) -> RoleConfig:
    return RoleConfig(
        name="gateway-dev",
        band=band,
        heartbeat=heartbeat,
        staleness_ms=staleness_ms,
        build=[],
        serve=[],
    )


def test_classify_reports_dead_stale_and_live(tmp_path) -> None:
    role = _role(PortBand(18100, 18109), heartbeat=True, staleness_ms=1000)

    dead = _record(pid=_dead_pid())
    assert classify_record(dead, role) is StalenessState.DEAD

    # Alive pid, heartbeat far in the past -> stale.
    stale = _record(pid=os.getpid(), last_seen_ms=now_ms() - 5000)
    assert classify_record(stale, role, now=now_ms()) is StalenessState.STALE

    # Alive pid, fresh heartbeat -> live.
    live = _record(pid=os.getpid(), last_seen_ms=now_ms())
    assert classify_record(live, role, now=now_ms()) is StalenessState.LIVE

    # A non-heartbeat role rests on pid-liveness alone: an old last_seen is still live.
    no_hb = _role(PortBand(18100, 18109), heartbeat=False)
    assert classify_record(stale, no_hb, now=now_ms()) is StalenessState.LIVE


def test_refresh_last_seen_advances_the_heartbeat(tmp_path) -> None:
    record = _record(last_seen_ms=1)
    write_record(record, home=tmp_path)

    updated = refresh_last_seen(record, at_ms=999999, home=tmp_path)
    assert updated.last_seen_ms == 999999

    persisted = read_record(record_path("gateway-dev", "alpha", home=tmp_path))
    assert persisted is not None
    assert persisted.last_seen_ms == 999999


def _config(band: PortBand) -> ProcsConfig:
    return ProcsConfig(
        resident={"engine": 8767, "gateway": 8000},
        roles={"scratch": _role(band, heartbeat=False)},
    )


def test_allocate_returns_a_free_band_port_and_skips_live_claims(tmp_path) -> None:
    # A small band of real, high, likely-free ports for a deterministic bind test.
    band = PortBand(18900, 18902)
    role = _role(band, heartbeat=False)
    config = _config(band)

    first = allocate_port("scratch", role, home=tmp_path, config=config)
    assert first in band

    # Record a LIVE claim on the allocated port; the next allocation must skip it.
    write_record(
        _record(role="scratch", name="claimant", port=first, pid=os.getpid()),
        home=tmp_path,
    )
    second = allocate_port("scratch", role, home=tmp_path, config=config)
    assert second in band and second != first


def test_allocate_raises_when_band_exhausted(tmp_path) -> None:
    band = PortBand(18900, 18901)
    role = _role(band, heartbeat=False)
    config = _config(band)
    # Claim every port in the band with live records.
    for i, port in enumerate(band):
        write_record(
            _record(role="scratch", name=f"c{i}", port=port, pid=os.getpid()),
            home=tmp_path,
        )
    with pytest.raises(RuntimeError, match="exhausted"):
        allocate_port("scratch", role, home=tmp_path, config=config)


def test_reserve_port_is_exclusive_across_back_to_back_callers(tmp_path) -> None:
    # The allocate-and-claim race closer: a held reservation blocks the SAME port,
    # so two back-to-back reservations (neither yet backed by a record) differ.
    # (The O_EXCL create is the concurrency arbiter; this proves the held-marker
    # exclusion that makes it race-free.)
    band = PortBand(18900, 18902)
    role = _role(band, heartbeat=False)
    config = _config(band)

    first = reserve_port("scratch", role, home=tmp_path, config=config)
    second = reserve_port("scratch", role, home=tmp_path, config=config)
    assert first.port in band
    assert second.port in band
    assert first.port != second.port
    assert first.path.exists()

    # allocate_port must also skip a live reservation, not just live records.
    allocated = allocate_port("scratch", role, home=tmp_path, config=config)
    assert allocated not in {first.port, second.port}


def test_commit_reservation_writes_record_and_clears_marker(tmp_path) -> None:
    band = PortBand(18900, 18902)
    role = _role(band, heartbeat=False)
    config = _config(band)

    reservation = reserve_port("scratch", role, home=tmp_path, config=config)
    record = _record(role="scratch", name="committed", port=reservation.port)
    commit_reservation(reservation, record, home=tmp_path)

    assert not reservation.path.exists()
    persisted = read_record(record_path("scratch", "committed", home=tmp_path))
    assert persisted is not None
    assert persisted.port == reservation.port


def test_release_reservation_frees_the_port(tmp_path) -> None:
    band = PortBand(18900, 18900)  # single-port band
    role = _role(band, heartbeat=False)
    config = _config(band)

    first = reserve_port("scratch", role, home=tmp_path, config=config)
    # The band is now exhausted by the held reservation ...
    with pytest.raises(RuntimeError, match="exhausted"):
        reserve_port("scratch", role, home=tmp_path, config=config)
    # ... until it is released.
    release_reservation(first)
    again = reserve_port("scratch", role, home=tmp_path, config=config)
    assert again.port == first.port


def test_stale_reservation_marker_is_reclaimable(tmp_path) -> None:
    band = PortBand(18900, 18900)
    role = _role(band, heartbeat=False)
    config = _config(band)

    stale = reserve_port("scratch", role, home=tmp_path, config=config)
    # Backdate the marker well beyond the TTL backstop; it must no longer block the
    # port even though its stored pid (this test process) is still alive.
    old = time.time() - 10_000_000
    os.utime(stale.path, (old, old))

    reclaimed = reserve_port("scratch", role, home=tmp_path, config=config)
    assert reclaimed.port == stale.port


def test_reserve_reclaims_a_marker_whose_reserver_pid_is_dead(tmp_path) -> None:
    band = PortBand(18900, 18900)  # single-port band
    role = _role(band, heartbeat=False)
    config = _config(band)

    # A fresh marker (well within the TTL backstop) stamped with a DEAD reserver
    # pid: liveness-aware reclaim must free the port immediately rather than wait
    # out the backstop, so a crashed reserver never wedges a band port.
    marker = tmp_path / "scratch-18900.reserved"
    marker.write_text(str(_dead_pid()), encoding="ascii")

    reclaimed = reserve_port("scratch", role, home=tmp_path, config=config)
    assert reclaimed.port == 18900


def test_port_free_and_reserve_skip_a_foreign_reuseaddr_listener(tmp_path) -> None:
    # Regression lock for the Windows collision the live dogfood caught: a real
    # SO_REUSEADDR listener NOT in the registry (a foreign resident gateway). The
    # old bind+SO_REUSEADDR free-check reported such a port FREE on Windows, so
    # reserve_port handed out a live foreign port. The connect-probe must catch it.
    foreign = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    foreign.bind(("127.0.0.1", 0))
    foreign.listen(1)
    held_port = foreign.getsockname()[1]
    try:
        # The foreign listener answers a connect, so the port reads as taken ...
        assert _port_is_free(held_port) is False
        # ... and a truly free port still reads as free.
        assert _port_is_free(_unused_port()) is True

        # reserve_port must SKIP the foreign-held port: a single-port band holding
        # only it is exhausted, never handed out to a colliding boot.
        band = PortBand(held_port, held_port)
        with pytest.raises(RuntimeError, match="exhausted"):
            reserve_port(
                "scratch",
                _role(band, heartbeat=False),
                home=tmp_path,
                config=_config(band),
            )
    finally:
        foreign.close()


def _unused_port() -> int:
    """An ephemeral port with no listener (bound then released), for a free probe."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
