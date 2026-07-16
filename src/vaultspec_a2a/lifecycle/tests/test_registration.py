"""Serve-path registration adoption (dev-process-registry P02.S03).

Real registry files under an isolated home, real process pid (this test process)
- no mocks. Proves the band-gated registration contract: a dev instance on a role
band port becomes a record; a resident/out-of-band instance registers nothing, so
production serve paths are inert.
"""

from __future__ import annotations

import os

from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registration import deregister_serve, refresh_registration, register_serve
from ..registry import read_record, record_path


def _config() -> ProcsConfig:
    return ProcsConfig(
        resident={"engine": 8767, "gateway": 8000},
        roles={
            "gateway-dev": RoleConfig(
                name="gateway-dev",
                band=PortBand(18100, 18109),
                heartbeat=True,
                staleness_ms=120000,
                build=[],
                serve=[],
            )
        },
    )


def test_register_serve_records_a_band_port_instance(tmp_path) -> None:
    record = register_serve(
        "gateway-dev", 18100, workspace="ws-a", home=tmp_path, config=_config()
    )
    assert record is not None
    assert record.role == "gateway-dev"
    assert record.pid == os.getpid()
    assert record.port == 18100
    persisted = read_record(record_path("gateway-dev", record.name, home=tmp_path))
    assert persisted is not None
    assert persisted.workspace == "ws-a"


def test_register_serve_ignores_a_resident_out_of_band_port(tmp_path) -> None:
    # 8000 is the resident gateway port, outside gateway-dev's band -> no record.
    record = register_serve("gateway-dev", 8000, home=tmp_path, config=_config())
    assert record is None
    assert not list(tmp_path.glob("*.json"))


def test_register_serve_ignores_an_unknown_role(tmp_path) -> None:
    record = register_serve("nonesuch", 18100, home=tmp_path, config=_config())
    assert record is None
    assert not list(tmp_path.glob("*.json"))


def test_refresh_and_deregister_round_trip(tmp_path) -> None:
    record = register_serve("gateway-dev", 18101, home=tmp_path, config=_config())
    assert record is not None

    refresh_registration(record, home=tmp_path)
    persisted = read_record(record_path("gateway-dev", record.name, home=tmp_path))
    assert persisted is not None
    assert persisted.last_seen_ms >= record.last_seen_ms

    deregister_serve(record, home=tmp_path)
    assert read_record(record_path("gateway-dev", record.name, home=tmp_path)) is None

    # Deregistering a None registration (resident instance) is a safe no-op.
    deregister_serve(None, home=tmp_path)
