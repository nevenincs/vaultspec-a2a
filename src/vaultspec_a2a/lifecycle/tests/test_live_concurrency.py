"""Live concurrency proof for the dev-process registry (dev-process-registry P02.S04).

The ADR's headline claim, proven end to end against real OS processes and real
loopback binds - no mocks, no fakes. Four registered engine+gateway stacks are
booted SEQUENTIALLY (each live record holds its port, so the next allocation must
pick a different one) and come up on distinct band ports without collision;
``procs list`` enumerates every one truthfully; a felled orphan reads DEAD and is
reaped while the live stacks survive; ``rerun`` rebuilds and re-registers on the
same port. This proves no-collision-across-allocations plus truthful
enumerate/reap/rerun - not simultaneous O_EXCL contention, which the reserve_port
unit tests cover. Every port is band-allocated through the registry and every pid
killed is one this test spawned - the live acceptance stack (18770/18110/18111) is
never touched.
"""

from __future__ import annotations

import socket
import sys
import time

from ..manager import attach, list_verdicts, rerun, serve_up, tree_kill
from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registry import StalenessState, list_records, read_record, record_path

# A representative serve command: a real child that binds its port and holds it.
_BIND_SERVE = (
    "import socket,sys,time;"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',int(sys.argv[1])));"
    "s.listen();"
    "time.sleep(120)"
)


def _role(name: str, band: tuple[int, int]) -> RoleConfig:
    return RoleConfig(
        name=name,
        band=PortBand(*band),
        heartbeat=False,
        staleness_ms=120000,
        build=[],
        serve=[sys.executable, "-c", _BIND_SERVE, "{port}"],
    )


def _stacks_config() -> ProcsConfig:
    # Two role bands inside the committed scratch range (18900-18999), so this
    # proof never contends the real dev bands or the live acceptance stack.
    return ProcsConfig(
        resident={"engine": 8767, "gateway": 8000},
        roles={
            "engine-dev": _role("engine-dev", (18960, 18969)),
            "gateway-dev": _role("gateway-dev", (18970, 18979)),
        },
    )


def _wait_listener(port: int, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _wait_pid_dead(pid: int, *, timeout: float = 10.0) -> bool:
    from ..discovery import is_pid_alive

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.05)
    return not is_pid_alive(pid)


def test_sequential_stacks_no_collision_reap_and_rerun(tmp_path) -> None:
    config = _stacks_config()
    spawned = []
    try:
        # Four engine+gateway stacks booted sequentially through the registry; each
        # live record holds its port, so no two land on the same one.
        e1 = serve_up(
            "engine-dev", "e1", home=tmp_path, config=config, ready_timeout=15
        )
        g1 = serve_up(
            "gateway-dev", "g1", home=tmp_path, config=config, ready_timeout=15
        )
        e2 = serve_up(
            "engine-dev", "e2", home=tmp_path, config=config, ready_timeout=15
        )
        g2 = serve_up(
            "gateway-dev", "g2", home=tmp_path, config=config, ready_timeout=15
        )
        spawned = [e1, g1, e2, g2]

        # (1) No collision: four distinct ports, each inside its own role band.
        assert len({r.port for r in spawned}) == 4
        assert {e1.port, e2.port} <= set(range(18960, 18970))
        assert {g1.port, g2.port} <= set(range(18970, 18980))

        # (2) procs list enumerates all four truthfully as LIVE.
        verdicts = {
            (v.record.role, v.record.name): v.state
            for v in list_verdicts(home=tmp_path, config=config)
        }
        assert len(verdicts) == 4
        assert all(state is StalenessState.LIVE for state in verdicts.values())

        # (3) A stale orphan: fell e2 out-of-band. Its record now reads DEAD ...
        tree_kill(e2.pid)
        assert _wait_pid_dead(e2.pid)
        after_kill = {
            (v.record.role, v.record.name): v.state
            for v in list_verdicts(home=tmp_path, config=config)
        }
        assert after_kill[("engine-dev", "e2")] is StalenessState.DEAD

        # ... and reap collects exactly that orphan, sparing the three live stacks.
        from ..manager import reap

        reaped = reap(home=tmp_path, config=config)
        assert {(r.role, r.name) for r in reaped} == {("engine-dev", "e2")}
        assert read_record(record_path("engine-dev", "e2", home=tmp_path)) is None
        assert len(list_records(tmp_path)) == 3

        # (4) rerun g1: felled, rebuilt (no build cmd), re-registered on the SAME port.
        g1b = rerun("g1", home=tmp_path, config=config)
        spawned = [e1, g1b, g2]
        assert g1b.port == g1.port
        assert g1b.pid != g1.pid
        assert _wait_listener(g1b.port)
        assert attach("g1", home=tmp_path).endpoint.endswith(str(g1b.port))
    finally:
        for record in spawned:
            tree_kill(record.pid)
