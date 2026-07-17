"""Gateway -> worker dispatch pairing verification (the master-bug guard).

Real registry files under an isolated home, real process liveness (this test's pid)
- no mocks. Pins the three verdicts: a band target is fine, an out-of-band target
with a live band worker is the mis-pairing that must refuse boot, and an out-of-band
target with no band worker is a warn-only plausible dev intent.
"""

from __future__ import annotations

import os

from ..pairing import DispatchPairingStatus, verify_dispatch_pairing
from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registry import ProcRecord, write_record


def _config() -> ProcsConfig:
    return ProcsConfig(
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


def _seed_live_band_worker(home) -> None:
    write_record(
        ProcRecord(
            name="wk", role="worker-dev", pid=os.getpid(), port=18110, owner="o"
        ),
        home=home,
    )


def test_pairing_ok_when_target_is_in_band(tmp_path) -> None:
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:18110", home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK
    assert msg == ""


def test_pairing_mispaired_when_out_of_band_and_a_band_worker_is_live(tmp_path) -> None:
    _seed_live_band_worker(tmp_path)
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:8001", home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.MISPAIRED
    # The message names the mis-target, the band worker being ignored, and the fix.
    assert "8001" in msg
    assert "worker-dev-wk" in msg
    assert "18110" in msg
    assert "--worker-url" in msg


def test_pairing_unpaired_when_out_of_band_and_no_band_worker(tmp_path) -> None:
    status, msg = verify_dispatch_pairing(
        "http://127.0.0.1:8001", home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.UNPAIRED
    assert "intentional" in msg


def test_pairing_ok_when_no_worker_dev_role(tmp_path) -> None:
    config = ProcsConfig(resident={}, roles={})
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1:8001", home=tmp_path, config=config
    )
    assert status is DispatchPairingStatus.OK


def test_pairing_ok_when_url_has_no_port(tmp_path) -> None:
    status, _ = verify_dispatch_pairing(
        "http://127.0.0.1", home=tmp_path, config=_config()
    )
    assert status is DispatchPairingStatus.OK
