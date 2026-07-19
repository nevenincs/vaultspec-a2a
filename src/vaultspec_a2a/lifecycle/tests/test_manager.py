"""Process-lifecycle verbs over the registry.

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
from pathlib import Path
from typing import Any

import pytest

from ...control.config import GATEWAY_URL_ENV, INTERNAL_TOKEN_ENV, WORKER_URL_ENV
from ..discovery import is_pid_alive
from ..manager import (
    _ENGINE_SERVICE_JSON_ENV,
    LifecycleError,
    _build_cwd_for,
    _serve_cwd_for,
    _serve_env,
    attach,
    kill,
    reap,
    rebuild,
    render_command,
    render_env,
    rerun,
    resolve,
    resume,
    serve_up,
    spawn,
    tree_kill,
)
from ..procs_config import PortBand, ProcsConfig, RoleConfig
from ..registry import (
    ProcRecord,
    list_records,
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


def test_spawn_rotates_an_over_cap_log_to_a_dot_one_sibling(tmp_path) -> None:
    """A redirect log already at the size cap is rotated, not appended forever."""
    from .. import manager as manager_module

    log_path = tmp_path / "big.log"
    log_path.write_bytes(b"x" * manager_module.SPAWN_LOG_CAP_BYTES)
    rotated_path = tmp_path / "big.log.1"
    assert not rotated_path.exists()

    process = spawn(
        [sys.executable, "-c", "print('fresh boot')"],
        cwd=tmp_path,
        log_path=str(log_path),
    )
    process.wait(timeout=10)

    assert rotated_path.exists()
    assert rotated_path.read_bytes() == b"x" * manager_module.SPAWN_LOG_CAP_BYTES
    # The fresh log holds only this boot's output - far under the cap.
    assert log_path.stat().st_size < manager_module.SPAWN_LOG_CAP_BYTES
    assert b"fresh boot" in log_path.read_bytes()


def test_spawn_does_not_rotate_a_log_under_the_cap(tmp_path) -> None:
    """A log well under the cap keeps appending - no spurious rotation."""
    log_path = tmp_path / "small.log"
    log_path.write_text("prior boot\n", encoding="utf-8")
    rotated_path = tmp_path / "small.log.1"

    process = spawn(
        [sys.executable, "-c", "print('this boot')"],
        cwd=tmp_path,
        log_path=str(log_path),
    )
    process.wait(timeout=10)

    assert not rotated_path.exists()
    contents = log_path.read_bytes()
    assert b"prior boot" in contents
    assert b"this boot" in contents


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


def test_kill_verb_deletes_the_record_log_file(tmp_path) -> None:
    """A killed record's runtime log is deleted - nothing will append to it again."""
    child = _sleeper()
    log_file = tmp_path / "killme.log"
    log_file.write_text("some prior boot's output\n", encoding="utf-8")
    try:
        write_record(
            _record(
                name="killme-log",
                pid=child.pid,
                port=18908,
                log_path=str(log_file),
            ),
            home=tmp_path,
        )
        kill("killme-log", home=tmp_path)
        assert wait_pid_dead(child.pid)
        assert not log_file.exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_kill_verb_tolerates_a_missing_log_file(tmp_path) -> None:
    """A record whose log_path was already removed must not fail the kill."""
    child = _sleeper()
    try:
        write_record(
            _record(
                name="killme-nolog",
                pid=child.pid,
                port=18909,
                log_path=str(tmp_path / "never-written.log"),
            ),
            home=tmp_path,
        )
        record = kill("killme-nolog", home=tmp_path)
        assert record.pid == child.pid
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


def test_reap_deletes_the_dead_records_log_but_keeps_the_live_ones(tmp_path) -> None:
    """Reap deletes a dead/stale record's log file but never a live one's."""
    corpse_log = tmp_path / "corpse.log"
    corpse_log.write_text("orphaned output\n", encoding="utf-8")
    write_record(
        _record(
            name="corpse-log", pid=_dead_pid(), port=18910, log_path=str(corpse_log)
        ),
        home=tmp_path,
    )
    child = _sleeper()
    alive_log = tmp_path / "alive.log"
    alive_log.write_text("still running\n", encoding="utf-8")
    try:
        write_record(
            _record(
                name="alive-log", pid=child.pid, port=18911, log_path=str(alive_log)
            ),
            home=tmp_path,
        )
        reaped = reap(home=tmp_path, config=_scratch_config())
        reaped_names = {r.name for r in reaped}
        assert "corpse-log" in reaped_names
        assert not corpse_log.exists()
        assert alive_log.exists()
    finally:
        tree_kill(child.pid)


# A real serve command that binds the given port and holds it until felled.
_BIND_SERVE = (
    "import socket,sys,time;"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',int(sys.argv[1])));"
    "s.listen();"
    "time.sleep(60)"
)


def _serve_config(serve: list[str], band: tuple[int, int]) -> ProcsConfig:
    role = RoleConfig(
        name="scratch",
        band=PortBand(*band),
        heartbeat=False,
        staleness_ms=120000,
        build=[],
        serve=serve,
    )
    return ProcsConfig(resident={}, roles={"scratch": role})


def test_serve_up_boots_registers_and_picks_distinct_ports(tmp_path) -> None:
    serve = [sys.executable, "-c", _BIND_SERVE, "{port}"]
    config = _serve_config(serve, band=(18990, 18992))

    first = serve_up(
        "scratch", "alpha", home=tmp_path, config=config, ready_timeout=15.0
    )
    second = serve_up(
        "scratch", "beta", home=tmp_path, config=config, ready_timeout=15.0
    )
    try:
        # Two live processes on two DIFFERENT band ports — the collision the race
        # would have caused cannot happen because reserve_port is exclusive.
        assert is_pid_alive(first.pid) and is_pid_alive(second.pid)
        assert first.port != second.port
        assert first.port in range(18990, 18993)
        assert second.port in range(18990, 18993)
        # Records committed, reservation markers cleared, listeners real.
        assert read_record(record_path("scratch", "alpha", home=tmp_path)) is not None
        assert not list(tmp_path.glob("*.reserved"))
        assert attach("alpha", home=tmp_path).endpoint.endswith(str(first.port))
    finally:
        tree_kill(first.pid)
        tree_kill(second.pid)


def test_serve_up_raises_when_no_band_port_yields_a_listener(tmp_path) -> None:
    # A serve command that exits immediately never binds; a 2-port band bounds the
    # retry loop so the exhaustion is fast and deterministic.
    config = _serve_config([sys.executable, "-c", "pass"], band=(18994, 18995))
    with pytest.raises(LifecycleError, match="no band port yielded a live listener"):
        serve_up("scratch", "doomed", home=tmp_path, config=config, ready_timeout=3.0)
    # Nothing registered, every reservation released.
    assert list_records(tmp_path) == []
    assert not list(tmp_path.glob("*.reserved"))


# A serve command that binds the port it reads from an env var (never argv).
_BIND_FROM_ENV = (
    "import socket,os,time;"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',int(os.environ['PROBEPORT'])));"
    "s.listen();"
    "time.sleep(60)"
)


def _serve_config_with_env(
    serve: list[str], band: tuple[int, int], env: dict[str, str]
) -> ProcsConfig:
    role = RoleConfig(
        name="scratch",
        band=PortBand(*band),
        heartbeat=False,
        staleness_ms=120000,
        build=[],
        serve=serve,
        env=env,
    )
    return ProcsConfig(resident={}, roles={"scratch": role})


def test_render_command_resolves_the_python_interpreter() -> None:
    rendered = render_command(
        ["{python}", "-m", "mod", "--flag", "{port}"], port=18100, workspace=""
    )
    assert rendered == [sys.executable, "-m", "mod", "--flag", "18100"]


def test_render_env_substitutes_port_and_workspace() -> None:
    env = render_env(
        {"VAULTSPEC_PORT": "{port}", "WS": "{workspace}", "K": "v"},
        port=18101,
        workspace="/w",
    )
    assert env == {"VAULTSPEC_PORT": "18101", "WS": "/w", "K": "v"}


def test_serve_env_carries_identity_and_rendered_role_env() -> None:
    role = RoleConfig(
        name="gateway-dev",
        band=PortBand(18100, 18109),
        heartbeat=True,
        staleness_ms=120000,
        build=[],
        serve=["x"],
        env={"VAULTSPEC_PORT": "{port}"},
    )
    env = _serve_env(role, port=18103, workspace="ws", name="g1", owner="sess-a")
    # Rendered role env plus the managed identity, so a self-registering child
    # converges onto the same (role, name)/owner record instead of a rival one.
    assert env["VAULTSPEC_PORT"] == "18103"
    assert env["VAULTSPEC_PROCS_NAME"] == "g1"
    assert env["VAULTSPEC_PROCS_OWNER"] == "sess-a"


def test_serve_env_injects_engine_service_json_only_when_set() -> None:
    role = RoleConfig(
        name="worker-dev",
        band=PortBand(18110, 18119),
        heartbeat=False,
        staleness_ms=120000,
        build=[],
        serve=["x"],
        env={"VAULTSPEC_WORKER_PORT": "{port}"},
    )
    with_seat = _serve_env(
        role,
        port=18110,
        workspace="ws",
        name="w1",
        owner="s",
        engine_service_json="C:/seat/service.json",
    )
    assert with_seat[_ENGINE_SERVICE_JSON_ENV] == "C:/seat/service.json"
    assert with_seat["VAULTSPEC_WORKER_PORT"] == "18110"
    # An unset seat injects nothing (records predating the field keep prior behaviour).
    without = _serve_env(role, port=18110, workspace="ws", name="w1", owner="s")
    assert _ENGINE_SERVICE_JSON_ENV not in without


def _pairing_role() -> RoleConfig:
    return RoleConfig(
        name="worker-dev",
        band=PortBand(18110, 18119),
        heartbeat=False,
        staleness_ms=120000,
        build=[],
        serve=["x"],
        env={},
    )


def test_serve_env_injects_gateway_url_and_reads_the_internal_token(tmp_path) -> None:
    token_file = tmp_path / "tok"
    token_file.write_text("s3cr3t\n")  # trailing newline must be stripped
    env = _serve_env(
        _pairing_role(),
        port=18110,
        workspace="",
        name="w",
        owner="o",
        internal_token_file=str(token_file),
        gateway_url="http://127.0.0.1:18100",
        worker_url="http://127.0.0.1:18110",
    )
    # The record carried only the PATH; the token is read here and injected.
    assert env[INTERNAL_TOKEN_ENV] == "s3cr3t"
    assert env[GATEWAY_URL_ENV] == "http://127.0.0.1:18100"
    assert env[WORKER_URL_ENV] == "http://127.0.0.1:18110"
    # Unset pairing injects nothing.
    bare = _serve_env(_pairing_role(), port=18110, workspace="", name="w", owner="o")
    assert INTERNAL_TOKEN_ENV not in bare
    assert GATEWAY_URL_ENV not in bare
    assert WORKER_URL_ENV not in bare


def test_serve_up_refuses_a_missing_token_file_with_no_residue(tmp_path) -> None:
    serve = [sys.executable, "-c", _BIND_SERVE, "{port}"]
    config = _serve_config(serve, band=(18990, 18992))
    # The token-file read happens after reserve_port but before spawn; the refusal
    # must leave no record, no reservation marker, and nothing spawned.
    with pytest.raises(LifecycleError, match="unreadable"):
        serve_up(
            "scratch",
            "w",
            home=tmp_path,
            config=config,
            internal_token_file=str(tmp_path / "does-not-exist"),
            ready_timeout=5.0,
        )
    assert list_records(tmp_path) == []
    assert not list(tmp_path.glob("*.reserved"))


def test_serve_env_fails_loud_on_a_missing_or_empty_token_file(tmp_path) -> None:
    with pytest.raises(LifecycleError, match="unreadable"):
        _serve_env(
            _pairing_role(),
            port=18110,
            workspace="",
            name="w",
            owner="o",
            internal_token_file=str(tmp_path / "does-not-exist"),
        )
    empty = tmp_path / "empty"
    empty.write_text("   \n")
    with pytest.raises(LifecycleError, match="empty"):
        _serve_env(
            _pairing_role(),
            port=18110,
            workspace="",
            name="w",
            owner="o",
            internal_token_file=str(empty),
        )


# A serve probe that records the injected pairing env vars, then binds the port so
# serve_up sees a live listener - proving the token (read from its file) and gateway
# url reached the child environment end to end.
_PAIRING_PROBE_SERVE = (
    "import socket,os,sys,time,pathlib;"
    "pathlib.Path(sys.argv[2]).write_text("
    "os.environ.get('VAULTSPEC_INTERNAL_TOKEN','')+'|'"
    "+os.environ.get('VAULTSPEC_GATEWAY_URL','')+'|'"
    "+os.environ.get('VAULTSPEC_WORKER_URL',''));"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',int(sys.argv[1])));s.listen();time.sleep(60)"
)


def test_serve_up_records_and_injects_the_worker_gateway_pairing(tmp_path) -> None:
    sentinel = tmp_path / "pairing.txt"
    token_file = tmp_path / "tok"
    token_file.write_text("tok-abc\n")
    serve = [sys.executable, "-c", _PAIRING_PROBE_SERVE, "{port}", str(sentinel)]
    config = _serve_config(serve, band=(18990, 18992))
    record = serve_up(
        "scratch",
        "w",
        home=tmp_path,
        config=config,
        internal_token_file=str(token_file),
        gateway_url="http://127.0.0.1:18100",
        worker_url="http://127.0.0.1:18110",
        ready_timeout=15.0,
    )
    try:
        assert record.internal_token_file == str(token_file)
        assert record.gateway_url == "http://127.0.0.1:18100"
        assert record.worker_url == "http://127.0.0.1:18110"
        persisted = read_record(record_path("scratch", "w", home=tmp_path))
        assert persisted is not None
        assert persisted.internal_token_file == str(token_file)
        assert persisted.gateway_url == "http://127.0.0.1:18100"
        assert persisted.worker_url == "http://127.0.0.1:18110"
        # The token was read from its file (stripped) and all three vars reached the
        # child's environment end to end.
        assert (
            sentinel.read_text()
            == "tok-abc|http://127.0.0.1:18100|http://127.0.0.1:18110"
        )
    finally:
        tree_kill(record.pid)


# A serve command that records the injected engine-discovery env var into a file,
# then binds the port so serve_up sees a live listener - proving the var reached the
# child process environment end to end.
_ENV_PROBE_SERVE = (
    "import socket,os,sys,time,pathlib;"
    "pathlib.Path(sys.argv[2]).write_text("
    "os.environ.get('VAULTSPEC_ENGINE_SERVICE_JSON',''));"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',int(sys.argv[1])));s.listen();time.sleep(60)"
)


def test_serve_up_records_and_injects_engine_service_json(tmp_path) -> None:
    sentinel = tmp_path / "seen-env.txt"
    seat = str(tmp_path / "engine-service.json")
    serve = [sys.executable, "-c", _ENV_PROBE_SERVE, "{port}", str(sentinel)]
    config = _serve_config(serve, band=(18990, 18992))
    record = serve_up(
        "scratch",
        "w",
        home=tmp_path,
        config=config,
        engine_service_json=seat,
        ready_timeout=15.0,
    )
    try:
        assert record.engine_service_json == seat
        persisted = read_record(record_path("scratch", "w", home=tmp_path))
        assert persisted is not None
        assert persisted.engine_service_json == seat
        # The listener implies the child already wrote the sentinel (write precedes
        # bind in the probe), so the var demonstrably reached the child env.
        assert sentinel.read_text() == seat
    finally:
        tree_kill(record.pid)


def test_resume_reproduces_recorded_engine_service_json(tmp_path) -> None:
    sentinel = tmp_path / "resume-env.txt"
    seat = str(tmp_path / "engine-service.json")
    serve = [sys.executable, "-c", _ENV_PROBE_SERVE, "{port}", str(sentinel)]
    config = _serve_config(serve, band=(18990, 18992))
    # A died record carrying an engine seat: resume must re-inject it from the record,
    # not depend on the resuming shell - the whole point of recording it.
    write_record(
        _record(
            name="rev",
            role="scratch",
            pid=_dead_pid(),
            port=18990,
            engine_service_json=seat,
        ),
        home=tmp_path,
    )
    updated = resume("rev", home=tmp_path, config=config)
    try:
        assert updated.engine_service_json == seat
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not sentinel.exists():
            time.sleep(0.05)
        assert sentinel.read_text() == seat
    finally:
        tree_kill(updated.pid)


def test_serve_up_injects_the_port_into_the_child_env(tmp_path) -> None:
    # The child binds a port it learns ONLY from the injected env var (never argv),
    # so a live listener proves serve_up wired render_env into the child environment.
    config = _serve_config_with_env(
        [sys.executable, "-c", _BIND_FROM_ENV],
        band=(18996, 18997),
        env={"PROBEPORT": "{port}"},
    )
    record = serve_up(
        "scratch", "envboot", home=tmp_path, config=config, ready_timeout=15.0
    )
    try:
        assert record.port in range(18996, 18998)
        assert attach("envboot", home=tmp_path).endpoint.endswith(str(record.port))
    finally:
        tree_kill(record.pid)


def test_build_cwd_uses_build_repo_and_serve_cwd_ignores_it(tmp_path) -> None:
    serve_dir = tmp_path / "serve"
    build_dir = tmp_path / "build"
    # Unset build_repo: build falls back to the serve repo (single-tree roles).
    only_serve = _record(name="one", role="scratch", repo=str(serve_dir))
    assert _build_cwd_for(only_serve) == serve_dir
    assert _serve_cwd_for(only_serve) == serve_dir
    # Distinct trees: build uses build_repo, serve keeps repo — the engine-dev split
    # where cargo builds the dashboard workspace but the wrapper serves from a2a.
    split = _record(
        name="two", role="scratch", repo=str(serve_dir), build_repo=str(build_dir)
    )
    assert _build_cwd_for(split) == build_dir
    assert _serve_cwd_for(split) == serve_dir


def test_rebuild_runs_the_build_in_the_build_repo_not_the_serve_repo(tmp_path) -> None:
    serve_dir = tmp_path / "serve"
    build_dir = tmp_path / "build"
    serve_dir.mkdir()
    build_dir.mkdir()
    home = tmp_path / "home"
    # A real build command that writes its own cwd to a sentinel, proving where the
    # subprocess actually ran — exactly what the single-repo record got wrong.
    build = [
        sys.executable,
        "-c",
        "import os, pathlib; pathlib.Path('where.txt').write_text(os.getcwd())",
    ]
    role = RoleConfig(
        name="scratch",
        band=PortBand(18900, 18999),
        heartbeat=False,
        staleness_ms=120000,
        build=build,
        serve=[],
    )
    config = ProcsConfig(resident={}, roles={"scratch": role})
    write_record(
        _record(
            name="eng",
            role="scratch",
            pid=os.getpid(),
            port=18900,
            repo=str(serve_dir),
            build_repo=str(build_dir),
        ),
        home=home,
    )

    rebuild("eng", home=home, config=config)

    sentinel = build_dir / "where.txt"
    assert sentinel.is_file()
    assert Path(sentinel.read_text()).resolve() == build_dir.resolve()
    assert not (serve_dir / "where.txt").exists()


def _require_repo_config(serve: list[str], band: tuple[int, int]) -> ProcsConfig:
    role = RoleConfig(
        name="scratch",
        band=PortBand(*band),
        heartbeat=False,
        staleness_ms=120000,
        build=[],
        serve=serve,
        require_repo=True,
    )
    return ProcsConfig(resident={}, roles={"scratch": role})


def test_serve_up_refuses_require_repo_role_without_repo(tmp_path) -> None:
    serve = [sys.executable, "-c", _BIND_SERVE, "{port}"]
    config = _require_repo_config(serve, band=(18990, 18992))
    # No repo passed: a data-seating role must refuse rather than default to the
    # project root (the silent fallback that seated a dev engine on the resident's
    # store). The refusal happens before any port reservation or spawn.
    with pytest.raises(LifecycleError, match="requires an explicit repo"):
        serve_up("scratch", "eng", home=tmp_path, config=config, ready_timeout=5.0)
    assert list_records(tmp_path) == []
    assert not list(tmp_path.glob("*.reserved"))


def test_serve_up_allows_a_require_repo_role_with_an_explicit_repo(tmp_path) -> None:
    serve = [sys.executable, "-c", _BIND_SERVE, "{port}"]
    config = _require_repo_config(serve, band=(18990, 18992))
    record = serve_up(
        "scratch",
        "eng",
        home=tmp_path,
        config=config,
        repo=str(tmp_path),
        ready_timeout=15.0,
    )
    try:
        assert record.repo == str(tmp_path)
    finally:
        tree_kill(record.pid)


def test_rerun_refuses_require_repo_role_before_killing(tmp_path) -> None:
    # A real live process behind a require_repo record with an empty repo: rerun must
    # refuse at entry (like serve_up/resume) WITHOUT first killing it - a lifecycle
    # verb that fells the process and then declines to restart it is the bug.
    child = _sleeper()
    try:
        config = _require_repo_config(
            [sys.executable, "-c", "import time; time.sleep(60)"], band=(18990, 18992)
        )
        write_record(
            _record(name="rr", role="scratch", pid=child.pid, port=18990, repo=""),
            home=tmp_path,
        )
        with pytest.raises(LifecycleError, match="requires an explicit repo"):
            rerun("rr", home=tmp_path, config=config)
        # The refusal happened before tree_kill: the process is still alive.
        assert is_pid_alive(child.pid)
    finally:
        tree_kill(child.pid)


def test_resume_refuses_a_require_repo_role_without_an_explicit_repo(tmp_path) -> None:
    config = _require_repo_config(
        [sys.executable, "-c", "import time; time.sleep(60)"], band=(18990, 18992)
    )
    # A died record whose repo is empty: resume must refuse rather than re-seat data
    # implicitly at the project root.
    write_record(
        _record(name="revive", role="scratch", pid=_dead_pid(), port=18990, repo=""),
        home=tmp_path,
    )
    with pytest.raises(LifecycleError, match="requires an explicit repo"):
        resume("revive", home=tmp_path, config=config)


def test_serve_up_captures_build_repo_into_the_record(tmp_path) -> None:
    serve = [sys.executable, "-c", _BIND_SERVE, "{port}"]
    config = _serve_config(serve, band=(18990, 18992))
    engine_repo = str(tmp_path / "engine")
    record = serve_up(
        "scratch",
        "eng",
        home=tmp_path,
        config=config,
        repo=str(tmp_path),
        build_repo=engine_repo,
        ready_timeout=15.0,
    )
    try:
        # The distinct build tree is captured on the record and survives the
        # write/read roundtrip, so rebuild/rerun later target it (not the serve repo).
        assert record.build_repo == engine_repo
        persisted = read_record(record_path("scratch", "eng", home=tmp_path))
        assert persisted is not None
        assert persisted.build_repo == engine_repo
    finally:
        tree_kill(record.pid)
