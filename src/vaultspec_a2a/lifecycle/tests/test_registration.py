"""Serve-path registration adoption.

Real registry files under an isolated home, real process pid (this test process)
- no mocks. Proves the band-gated registration contract: a dev instance on a role
band port becomes a record; a resident/out-of-band instance registers nothing, so
production serve paths are inert.
"""

from __future__ import annotations

import os
from dataclasses import replace

from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registration import deregister_serve, refresh_registration, register_serve
from ..registry import ProcRecord, read_record, record_path, write_record


def _config() -> ProcsConfig:
    return ProcsConfig(
        resident={"engine": 8767, "gateway": 18000, "worker": 18001},
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


def test_register_serve_preserves_operator_fields_on_convergence(tmp_path) -> None:
    # A record serve_up already committed, carrying operator-owned fields.
    seeded = ProcRecord(
        name="g1",
        role="gateway-dev",
        pid=os.getpid(),
        port=18100,
        repo="R:/serve",
        build_repo="B:/build",
        workspace="ws",
        build_sha="deadbee",
        command=["old", "command"],
        started_at_ms=111,
        last_seen_ms=111,
        log_path="L:/gw.log",
        owner="sess-a",
        engine_service_json="E:/svc.json",
        internal_token_file="T:/tok",
        gateway_url="http://127.0.0.1:18100",
    )
    write_record(seeded, home=tmp_path)

    # The serving child self-registers on the same (role, name, owner).
    converged = register_serve(
        "gateway-dev",
        18100,
        name="g1",
        owner="sess-a",
        command=["python", "-m", "vaultspec_a2a.cli.main", "serve"],
        home=tmp_path,
        config=_config(),
    )
    assert converged is not None
    # Self-registration owns the runtime identity...
    assert converged.pid == os.getpid()
    assert converged.command == ["python", "-m", "vaultspec_a2a.cli.main", "serve"]
    assert converged.last_seen_ms >= 111
    # ...and PRESERVES every operator-supplied field (the clobber bug that killed
    # gateway/worker logs mid-incident).
    assert converged.log_path == "L:/gw.log"
    assert converged.repo == "R:/serve"
    assert converged.build_repo == "B:/build"
    assert converged.workspace == "ws"
    assert converged.build_sha == "deadbee"
    assert converged.engine_service_json == "E:/svc.json"
    assert converged.internal_token_file == "T:/tok"
    assert converged.gateway_url == "http://127.0.0.1:18100"
    assert converged.started_at_ms == 111  # the real boot time, not reset
    # Persisted, so a later resume/rerun inherits the preserved fields (and redirects
    # output, since log_path survives).
    persisted = read_record(record_path("gateway-dev", "g1", home=tmp_path))
    assert persisted == converged


def test_register_serve_convergence_without_command_keeps_existing(tmp_path) -> None:
    write_record(
        ProcRecord(
            name="g2",
            role="gateway-dev",
            pid=os.getpid(),
            port=18102,
            command=["keep", "me"],
            owner="o",
            log_path="L:/x.log",
        ),
        home=tmp_path,
    )
    converged = register_serve(
        "gateway-dev", 18102, name="g2", owner="o", home=tmp_path, config=_config()
    )
    assert converged is not None
    # No command passed -> the existing command is preserved, not blanked.
    assert converged.command == ["keep", "me"]
    assert converged.log_path == "L:/x.log"


def test_refresh_registration_preserves_a_record_that_landed_after_it(tmp_path) -> None:
    # The self-registering process's in-memory record (built during the boot race,
    # before serve_up committed) carries defaults only.
    stale = ProcRecord(
        name="g", role="gateway-dev", pid=os.getpid(), port=18100, owner="o"
    )
    write_record(stale, home=tmp_path)
    # serve_up then commits the richer operator-supplied record on the same key.
    full = replace(
        stale,
        log_path="L:/gw.log",
        internal_token_file="T:/tok",
        gateway_url="http://x:18100",
    )
    write_record(full, home=tmp_path)

    # A heartbeat must re-read the live record, NOT re-clobber it with the stale copy.
    refresh_registration(stale, home=tmp_path)

    after = read_record(record_path("gateway-dev", "g", home=tmp_path))
    assert after is not None
    assert after.internal_token_file == "T:/tok"
    assert after.log_path == "L:/gw.log"
    assert after.gateway_url == "http://x:18100"
    assert after.last_seen_ms >= full.last_seen_ms


def test_register_serve_refuses_convergence_under_foreign_live_owner(tmp_path) -> None:
    # A live foreign-owned record (this test's pid, a different owner) must not be
    # rewritten by a converging registration under a different owner.
    foreign = ProcRecord(
        name="fg",
        role="gateway-dev",
        pid=os.getpid(),
        port=18100,
        owner="other-session",
        log_path="L:/keep.log",
    )
    write_record(foreign, home=tmp_path)

    result = register_serve(
        "gateway-dev", 18100, name="fg", owner="me", home=tmp_path, config=_config()
    )
    assert result is None
    on_disk = read_record(record_path("gateway-dev", "fg", home=tmp_path))
    assert on_disk is not None
    assert on_disk.owner == "other-session"
    assert on_disk.log_path == "L:/keep.log"


def test_register_serve_ignores_a_resident_out_of_band_port(tmp_path) -> None:
    # 18000 is the resident gateway port, outside gateway-dev's band -> no record.
    record = register_serve("gateway-dev", 18000, home=tmp_path, config=_config())
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
