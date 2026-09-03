"""Gateway <-> worker dispatch pairing verification (the master-bug guard).

Real registry files under an isolated home, real process liveness (this test's pid)
- no mocks. Pins the three verdicts for the gateway -> worker direction: a band
target is fine, an out-of-band target with a live band worker is the mis-pairing
that must refuse boot, and an out-of-band target with no band worker is a warn-only
plausible dev intent. The worker -> gateway direction
(``resolve_worker_gateway_target``) mirrors the same three verdicts plus the
auto-learn behaviour unique to that side.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from ..pairing import (
    DispatchPairingStatus,
    resolve_worker_gateway_target,
    verify_dispatch_pairing,
)
from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registry import ProcRecord, write_record

if TYPE_CHECKING:
    from pathlib import Path

# A band gateway-dev port (18100-18109), so condition (a) holds and the guard runs.
_BAND_GATEWAY_PORT = 18100
# A band worker-dev port (18110-18119), the worker-side mirror of the constant above.
_BAND_WORKER_PORT = 18110


def _config() -> ProcsConfig:
    def _role(name: str, band: PortBand) -> RoleConfig:
        return RoleConfig(
            name=name,
            band=band,
            heartbeat=False,
            staleness_ms=120000,
            build=[],
            serve=[],
        )

    return ProcsConfig(
        resident={},
        roles={
            "gateway-dev": _role("gateway-dev", PortBand(18100, 18109)),
            "worker-dev": _role("worker-dev", PortBand(18110, 18119)),
        },
    )


def _seed_band_worker(home: Path, *, pid: int) -> None:
    write_record(
        ProcRecord(name="wk", role="worker-dev", pid=pid, port=18110, owner="o"),
        home=home,
    )


def _seed_band_gateway(
    home: Path, *, pid: int, name: str = "gw", port: int = 18100
) -> None:
    write_record(
        ProcRecord(name=name, role="gateway-dev", pid=pid, port=port, owner="o"),
        home=home,
    )


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_pairing_ok_when_target_is_in_band(tmp_path: Path) -> None:
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:18110", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK
    assert msg == ""


def test_pairing_exempts_a_resident_out_of_band_gateway(tmp_path: Path) -> None:
    # A resident gateway (port 18000, outside the gateway-dev band) is never guarded,
    # even dispatching out-of-band with a live band worker present.
    _seed_band_worker(tmp_path, pid=os.getpid())
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1:18001", 18000, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK


def test_pairing_mispaired_when_out_of_band_and_a_band_worker_is_live(
    tmp_path: Path,
) -> None:
    _seed_band_worker(tmp_path, pid=os.getpid())
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:18001", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.MISPAIRED
    # The message names the mis-target, the band worker being ignored, and the fix.
    assert "18001" in msg
    assert "worker-dev-wk" in msg
    assert "18110" in msg
    assert "--worker-url" in msg


def test_pairing_unpaired_when_out_of_band_and_no_band_worker(tmp_path: Path) -> None:
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:18001", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.UNPAIRED
    assert "intentional" in msg


def test_pairing_unpaired_when_the_band_worker_record_is_dead(tmp_path: Path) -> None:
    # A band worker record whose pid is dead is NOT a live pairing target, so an
    # out-of-band gateway is UNPAIRED (warn), not MISPAIRED (refuse).
    _seed_band_worker(tmp_path, pid=_dead_pid())
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1:18001", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.UNPAIRED


def test_pairing_ok_when_no_worker_dev_role(tmp_path: Path) -> None:
    config = ProcsConfig(
        resident={},
        roles={
            "gateway-dev": RoleConfig(
                name="gateway-dev",
                band=PortBand(18100, 18109),
                heartbeat=False,
                staleness_ms=120000,
                build=[],
                serve=[],
            )
        },
    )
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1:18001", _BAND_GATEWAY_PORT, home=tmp_path, config=config
    )
    assert status is DispatchPairingStatus.OK


def test_pairing_ok_when_url_has_no_port(tmp_path: Path) -> None:
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK


# --- worker -> gateway direction (resolve_worker_gateway_target) -----------------


def test_worker_pairing_ok_when_target_is_already_in_band(tmp_path: Path) -> None:
    url, status, msg = resolve_worker_gateway_target(
        "http://127.0.0.1:18100",
        gateway_url_explicit=False,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.OK
    assert url == "http://127.0.0.1:18100"
    assert msg == ""


def test_worker_pairing_ok_when_not_a_band_worker_port(tmp_path: Path) -> None:
    # A resident or ad-hoc worker port is never guarded, even with a live band
    # gateway registered and a resident-shaped default target.
    _seed_band_gateway(tmp_path, pid=os.getpid())
    url, status, _ = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=False,
        worker_port=18001,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.OK
    assert url == "http://127.0.0.1:18000"


def test_worker_pairing_learns_the_sole_live_band_gateway(tmp_path: Path) -> None:
    # The reported bug: an unconfigured band worker auto-derives the resident
    # default (18000) while a real dev gateway is live on 18100. It should LEARN
    # the live band gateway rather than keep heartbeating the resident default.
    _seed_band_gateway(tmp_path, pid=os.getpid(), name="gw", port=18100)
    url, status, msg = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=False,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.OK
    assert url == "http://127.0.0.1:18100"
    assert "learned" in msg
    assert "gateway-dev-gw" in msg


def test_worker_pairing_unpaired_when_unconfigured_and_no_live_band_gateway(
    tmp_path: Path,
) -> None:
    # A worker legitimately started before its gateway - nothing to learn yet.
    url, status, msg = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=False,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.UNPAIRED
    assert url == "http://127.0.0.1:18000"
    assert "intentional" in msg


def test_worker_pairing_mispaired_when_unconfigured_and_ambiguous(
    tmp_path: Path,
) -> None:
    # Two live band gateways: auto-learning cannot safely pick one - refuse to boot
    # rather than guess.
    _seed_band_gateway(tmp_path, pid=os.getpid(), name="gw-a", port=18100)
    _seed_band_gateway(tmp_path, pid=os.getpid(), name="gw-b", port=18101)
    url, status, msg = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=False,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.MISPAIRED
    assert url == "http://127.0.0.1:18000"
    assert "MULTIPLE" in msg


def test_worker_pairing_mispaired_when_explicit_and_a_different_gateway_is_live(
    tmp_path: Path,
) -> None:
    # An explicit-but-wrong target (operator or spawning-gateway intent) is never
    # silently overridden; it fails loud instead, mirroring the gateway-side guard.
    _seed_band_gateway(tmp_path, pid=os.getpid(), name="gw", port=18100)
    url, status, msg = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=True,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.MISPAIRED
    assert url == "http://127.0.0.1:18000"
    assert "18000" in msg
    assert "gateway-dev-gw" in msg
    assert "--gateway-url" in msg


def test_worker_pairing_unpaired_when_explicit_and_no_live_band_gateway(
    tmp_path: Path,
) -> None:
    url, status, msg = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=True,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.UNPAIRED
    assert url == "http://127.0.0.1:18000"
    assert "intentional" in msg


def test_worker_pairing_unpaired_when_the_band_gateway_record_is_dead(
    tmp_path: Path,
) -> None:
    _seed_band_gateway(tmp_path, pid=_dead_pid())
    url, status, _ = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=False,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.UNPAIRED
    assert url == "http://127.0.0.1:18000"


def test_worker_pairing_ok_when_no_gateway_dev_role(tmp_path: Path) -> None:
    config = ProcsConfig(
        resident={},
        roles={
            "worker-dev": RoleConfig(
                name="worker-dev",
                band=PortBand(18110, 18119),
                heartbeat=False,
                staleness_ms=120000,
                build=[],
                serve=[],
            )
        },
    )
    url, status, _ = resolve_worker_gateway_target(
        "http://127.0.0.1:18000",
        gateway_url_explicit=False,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=config,
    )
    assert status is DispatchPairingStatus.OK
    assert url == "http://127.0.0.1:18000"


def test_worker_pairing_ok_when_url_has_no_port(tmp_path: Path) -> None:
    url, status, _ = resolve_worker_gateway_target(
        "http://127.0.0.1",
        gateway_url_explicit=False,
        worker_port=_BAND_WORKER_PORT,
        home=tmp_path,
        config=_config(),
    )
    assert status is DispatchPairingStatus.OK
    assert url == "http://127.0.0.1"
