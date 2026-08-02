"""Registry-backed endpoint resolution against real listeners and records.

Every service here is a real spawned HTTP server; every record is written
through the production registry writer into an isolated home. The refusals -
stale heartbeat, dead pid, unanswering port - are exercised against the real
OS, not simulated.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from ...lifecycle import ProcRecord, now_ms, write_record
from ..endpoints import resolve_service

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SERVER_SCRIPT = (
    "import http.server\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    "        code = 200 if self.path == '/health' else 404\n"
    "        self.send_response(code); self.end_headers(); self.wfile.write(b'ok')\n"
    "    def log_message(self, *args):\n"
    "        pass\n"
    "srv = http.server.HTTPServer(('127.0.0.1', 0), H)\n"
    "print(srv.server_address[1], flush=True)\n"
    "srv.serve_forever()\n"
)


@pytest.fixture
def health_server() -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        [sys.executable, "-c", _SERVER_SCRIPT],
        stdout=subprocess.PIPE,
        text=True,
    )
    yield process
    process.kill()
    process.wait(timeout=60)


def _server_port(process: subprocess.Popen[str]) -> int:
    assert process.stdout is not None
    line = process.stdout.readline().strip()
    assert line.isdigit(), f"server did not report a port: {line!r}"
    return int(line)


def _record(
    name: str, *, pid: int, port: int, last_seen_ms: int, role: str = "gateway-dev"
) -> ProcRecord:
    return ProcRecord(
        name=name, role=role, pid=pid, port=port, last_seen_ms=last_seen_ms
    )


def test_live_record_with_answering_health_resolves(
    tmp_path: Path, health_server: subprocess.Popen[str]
) -> None:
    port = _server_port(health_server)
    write_record(
        _record("g1", pid=health_server.pid, port=port, last_seen_ms=now_ms()),
        home=tmp_path,
    )
    resolved = resolve_service("gateway-dev", home=tmp_path)
    assert resolved is not None
    assert resolved.url == f"http://127.0.0.1:{port}"
    assert resolved.record is not None and resolved.record.name == "g1"


def test_stale_heartbeat_is_refused_despite_an_answering_server(
    tmp_path: Path, health_server: subprocess.Popen[str]
) -> None:
    """A frozen heartbeat disqualifies a record even while its port answers.

    This is the stale-record precedent: a live listener with a dead heartbeat
    writer must not be trusted, exactly as the production resolver refuses it.
    """
    port = _server_port(health_server)
    write_record(
        _record(
            "g1",
            pid=health_server.pid,
            port=port,
            last_seen_ms=now_ms() - 3_600_000,
        ),
        home=tmp_path,
    )
    assert resolve_service("gateway-dev", home=tmp_path) is None


def test_dead_pid_is_refused(tmp_path: Path) -> None:
    corpse = subprocess.Popen([sys.executable, "-c", "pass"])
    corpse.wait(timeout=60)
    write_record(
        _record("g1", pid=corpse.pid, port=1, last_seen_ms=now_ms()), home=tmp_path
    )
    assert resolve_service("gateway-dev", home=tmp_path) is None


def test_unanswering_port_is_passed_over_for_a_healthy_sibling(
    tmp_path: Path, health_server: subprocess.Popen[str]
) -> None:
    """The freshest record does not win by freshness alone; health decides.

    The fresher record points at a port nothing serves; the slightly older one
    answers. Resolution must pass over the broken record instead of returning
    a URL that cannot work.
    """
    port = _server_port(health_server)
    with_listener = now_ms() - 5_000
    without_listener = now_ms()
    write_record(
        _record("broken", pid=os.getpid(), port=1, last_seen_ms=without_listener),
        home=tmp_path,
    )
    write_record(
        _record(
            "healthy", pid=health_server.pid, port=port, last_seen_ms=with_listener
        ),
        home=tmp_path,
    )
    resolved = resolve_service("gateway-dev", home=tmp_path, health_timeout_s=1.0)
    assert resolved is not None
    assert resolved.record is not None and resolved.record.name == "healthy"


def test_environment_override_keeps_the_last_word(tmp_path: Path) -> None:
    """An explicit override resolves verbatim, with no probe and no registry.

    Exercised through a real subprocess so the environment is genuinely set at
    interpreter start rather than mutated in-process.
    """
    script = (
        "from vaultspec_a2a.testing.endpoints import resolve_gateway_url\n"
        "resolved = resolve_gateway_url()\n"
        "assert resolved is not None and resolved.record is None\n"
        "print(resolved.url, flush=True)\n"
    )
    env = dict(os.environ)
    env["VAULTSPEC_GATEWAY_URL"] = "http://127.0.0.1:59999/"
    env["VAULTSPEC_PROCS_HOME"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=True,
    )
    assert completed.stdout.strip() == "http://127.0.0.1:59999"


def test_no_records_resolves_to_none(tmp_path: Path) -> None:
    started = time.monotonic()
    assert resolve_service("gateway-dev", home=tmp_path) is None
    assert time.monotonic() - started < 30.0
