"""Gateway -> worker dispatch pairing verification (the master-bug guard).

Real registry files under an isolated home, real process liveness (this test's pid)
- no mocks. Pins the three verdicts: a band target is fine, an out-of-band target
with a live band worker is the mis-pairing that must refuse boot, and an out-of-band
target with no band worker is a warn-only plausible dev intent.
"""

from __future__ import annotations

import os
import subprocess
import sys

from ..pairing import DispatchPairingStatus, verify_dispatch_pairing
from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registry import ProcRecord, write_record

# A band gateway-dev port (18100-18109), so condition (a) holds and the guard runs.
_BAND_GATEWAY_PORT = 18100


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


def _seed_band_worker(home, *, pid: int) -> None:
    write_record(
        ProcRecord(name="wk", role="worker-dev", pid=pid, port=18110, owner="o"),
        home=home,
    )


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_pairing_ok_when_target_is_in_band(tmp_path) -> None:
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:18110", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK
    assert msg == ""


def test_pairing_exempts_a_resident_out_of_band_gateway(tmp_path) -> None:
    # A resident gateway (port 18000, outside the gateway-dev band) is never guarded,
    # even dispatching out-of-band with a live band worker present.
    _seed_band_worker(tmp_path, pid=os.getpid())
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1:18001", 18000, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK


def test_pairing_mispaired_when_out_of_band_and_a_band_worker_is_live(tmp_path) -> None:
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


def test_pairing_unpaired_when_out_of_band_and_no_band_worker(tmp_path) -> None:
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:18001", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.UNPAIRED
    assert "intentional" in msg


def test_pairing_unpaired_when_the_band_worker_record_is_dead(tmp_path) -> None:
    # A band worker record whose pid is dead is NOT a live pairing target, so an
    # out-of-band gateway is UNPAIRED (warn), not MISPAIRED (refuse).
    _seed_band_worker(tmp_path, pid=_dead_pid())
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1:18001", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.UNPAIRED


def test_pairing_ok_when_no_worker_dev_role(tmp_path) -> None:
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


def test_pairing_ok_when_url_has_no_port(tmp_path) -> None:
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1", _BAND_GATEWAY_PORT, home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK
