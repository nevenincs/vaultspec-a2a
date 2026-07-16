"""Process-lifecycle verbs over the registry (dev-process-registry P01.S02).

Real subprocesses, real loopback sockets, and real registry files - no mocks.
Every liveness assertion runs against a genuine OS process this test spawned:
``tree_kill`` fells a real sleeping child, ``resume`` re-spawns a real serve
command, and ``reap`` distinguishes a dead child from this live test process.
No pid is ever killed except one this module started.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import Any

import pytest

from ..discovery import is_pid_alive
from ..manager import (
    LifecycleError,
    attach,
    kill,
    reap,
    render_command,
    resolve,
    resume,
    tree_kill,
)
from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registry import (
    ProcRecord,
    now_ms,
    read_record,
    record_path,
    write_record,
)


def wait_pid_dead(pid: int, *, timeout: float = 10.0) -> bool:
    """Poll until *pid* is no longer a live process, or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.05)
    return not is_pid_alive(pid)


def _sleeper() -> subprocess.Popen[bytes]:
    """Spawn a real child that stays alive until killed."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _record(**overrides: Any) -> ProcRecord:
    base: dict[str, Any] = {
        "name": "alpha",
        "role": "scratch",
        "pid": os.getpid(),
        "port": 18900,
        "owner": "session-a",
        "started_at_ms": now_ms(),
        "last_seen_ms": now_ms(),
    }
    base.update(overrides)
    return ProcRecord(**base)


def _scratch_config(serve: list[str] | None = None) -> ProcsConfig:
    role = RoleConfig(
        name="scratch",
        band=PortBand(18900, 18999),
        heartbeat=False,
        staleness_ms=120000,
        build=[],
        serve=serve if serve is not None else [],
    )
    return ProcsConfig(resident={}, roles={"scratch": role})


def test_render_command_substitutes_port_and_workspace() -> None:
    rendered = render_command(
        ["serve", "--port", "{port}", "--ws", "{workspace}"],
        port=18901,
        workspace="/tmp/ws",
    )
    assert rendered == ["serve", "--port", "18901", "--ws", "/tmp/ws"]


def test_resolve_finds_unique_and_rejects_missing_and_ambiguous(tmp_path) -> None:
    write_record(_record(name="alpha", role="scratch", port=18900), home=tmp_path)
    assert resolve("alpha", home=tmp_path).name == "alpha"

    with pytest.raises(LifecycleError, match="no registry record named"):
        resolve("nope", home=tmp_path)

    # Same name under two roles -> ambiguous, must be qualified.
    write_record(_record(name="alpha", role="worker-dev", port=18110), home=tmp_path)
    with pytest.raises(LifecycleError, match="ambiguous"):
        resolve("alpha", home=tmp_path)
    # The fully-qualified form disambiguates.
    assert resolve("worker-dev-alpha", home=tmp_path).role == "worker-dev"


def test_tree_kill_fells_a_live_child_and_is_idempotent_on_dead() -> None:
    child = _sleeper()
    try:
        assert tree_kill(child.pid) is True
        assert wait_pid_dead(child.pid)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    # A pid that is already dead is a success, not an error.
    assert tree_kill(child.pid) is True


def test_kill_verb_removes_the_record_after_felling_the_tree(tmp_path) -> None:
    child = _sleeper()
    try:
        write_record(_record(name="killme", pid=child.pid, port=18902), home=tmp_path)
        record = kill("killme", home=tmp_path)
        assert record.pid == child.pid
        assert wait_pid_dead(child.pid)
        assert read_record(record_path("scratch", "killme", home=tmp_path)) is None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_attach_succeeds_on_a_bound_port_and_fails_on_a_dead_pid(tmp_path) -> None:
    # A real bound port held by this (live) process.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    bound_port = sock.getsockname()[1]
    try:
        write_record(
            _record(name="live", pid=os.getpid(), port=bound_port), home=tmp_path
        )
        verdict = attach("live", home=tmp_path)
        assert verdict.endpoint == f"http://127.0.0.1:{bound_port}"
    finally:
        sock.close()

    # A dead pid must refuse attach rather than hand back a stale endpoint.
    write_record(_record(name="gone", pid=_dead_pid(), port=18903), home=tmp_path)
    with pytest.raises(LifecycleError, match="is not alive"):
        attach("gone", home=tmp_path)


def test_resume_restarts_a_died_record_on_its_original_port(tmp_path) -> None:
    original_port = 18904
    record = _record(
        name="revive",
        pid=_dead_pid(),
        port=original_port,
        workspace="ws-x",
    )
    write_record(record, home=tmp_path)

    config = _scratch_config(
        serve=[sys.executable, "-c", "import time; time.sleep(60)"]
    )
    updated = resume("revive", home=tmp_path, config=config)
    try:
        # A brand-new live pid, same port and workspace preserved.
        assert updated.pid != record.pid
        assert updated.port == original_port
        assert updated.workspace == "ws-x"
        persisted = read_record(record_path("scratch", "revive", home=tmp_path))
        assert persisted is not None
        assert persisted.pid == updated.pid
    finally:
        tree_kill(updated.pid)

    # Resuming a live process is refused.
    child = _sleeper()
    try:
        write_record(_record(name="up", pid=child.pid, port=18905), home=tmp_path)
        with pytest.raises(LifecycleError, match="still alive"):
            resume("up", home=tmp_path, config=config)
    finally:
        tree_kill(child.pid)


def test_reap_clears_dead_and_stale_but_keeps_live(tmp_path) -> None:
    write_record(_record(name="corpse", pid=_dead_pid(), port=18906), home=tmp_path)
    child = _sleeper()
    try:
        write_record(_record(name="alive", pid=child.pid, port=18907), home=tmp_path)
        reaped = reap(home=tmp_path, config=_scratch_config())
        reaped_names = {r.name for r in reaped}
        assert "corpse" in reaped_names
        assert "alive" not in reaped_names
        assert read_record(record_path("scratch", "corpse", home=tmp_path)) is None
        assert read_record(record_path("scratch", "alive", home=tmp_path)) is not None
    finally:
        tree_kill(child.pid)
