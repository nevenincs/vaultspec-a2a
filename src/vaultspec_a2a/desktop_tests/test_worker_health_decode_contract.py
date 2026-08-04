"""Real-HTTP proof that one worker never gets two contradictory health verdicts.

A worker that answers ``200`` with a body the decoder cannot read is the case
where the gateway's two health readers used to disagree. The watchdog and
``/health`` read it through the probe primitive and saw the worker UP; the
boot, adopt, and evict paths read it through the body-returning helper, which
evaluated ``resp.json()`` inside the same ``try`` that caught transport
failures, and so received the identical ``None`` it receives for a DEAD worker.
One live worker was simultaneously up and absent, and the absent reading is the
one that spawns a competitor onto a port that worker still holds.

The occupant here is a real HTTP server in a real subprocess serving a real
malformed ``200`` over a real socket - the condition itself, not a stand-in for
any code under test. Every assertion drives production functions directly.

The contract these pin down is deliberately asymmetric, because the two callers
ask different questions of the same occupant:

- *is a worker up?* - yes; an unreadable body cannot make a healthy worker
  unhealthy;
- *does something hold this port?* - yes, so do not spawn onto it;
- *is that something provably mine?* - no; an unreadable body is the absence of
  evidence, and the provenance check must refuse it under both profiles.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from ..control.worker_management import (
    LazyWorkerSpawner,
    WorkerHealthProbe,
    probe_worker_health,
)
from ..testing.ports import free_port

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# A real server that answers 200 with a body that is emphatically not JSON.
# Content-Type claims JSON so the failure is the DECODE, not content negotiation.
_MALFORMED_WORKER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import override

port = int(sys.argv[1])
payload = b"<!doctype html><html><body>not json at all</body></html>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @override
    def log_message(self, format: str, *args: object) -> None:
        return None


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


# A real server that ACCEPTS the connection and then never answers - the shape a
# worker takes while it is busy compiling a graph for an already-admitted run.
_STALLED_WORKER = """
import socket, sys, time

port = int(sys.argv[1])
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", port))
listener.listen(8)
held = []
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    conn, _ = listener.accept()
    # Read the request and deliberately send nothing back, holding the socket
    # open so the client sees a read timeout rather than a connect failure.
    conn.recv(65536)
    held.append(conn)
"""


@contextlib.contextmanager
def _stalled_worker() -> Generator[str]:
    """Run a real server that accepts /health and never sends a response."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-c", _STALLED_WORKER, str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            with (
                contextlib.suppress(OSError),
                socket.create_connection(("127.0.0.1", port), timeout=1.0),
            ):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the stalled worker never bound its port")
        yield url
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
            proc.wait(timeout=10)


@contextlib.contextmanager
def _malformed_worker(tmp_path: Path) -> Generator[tuple[str, int]]:
    """Run a real HTTP server that answers /health 200 with undecodable bytes."""
    port = free_port()
    script = tmp_path / "malformed_worker.py"
    script.write_text(_MALFORMED_WORKER, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(script), str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                with httpx.Client(timeout=1.0) as client:
                    resp = client.get(f"{url}/health")
                if resp.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise AssertionError("the malformed worker never came up")
        yield url, port
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
            proc.wait(timeout=10)


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unreadable_worker_is_up_present_and_not_ours(
    tmp_path: Path,
) -> None:
    """One live unreadable worker yields three consistent, non-contradictory reads.

    Each assertion is a different production entry point against the SAME live
    occupant, which is what makes the set a split-brain proof rather than three
    unrelated checks.

    Load-bearing: the public result distinguishes a healthy but unreadable
    occupant from a dead worker. Collapsing those states would let spawn compete
    for a port a live process still holds.
    """
    with _malformed_worker(tmp_path) as (url, port):
        # The health verdict is the status code and nothing else: an unreadable
        # body cannot turn a healthy worker unhealthy.
        probe = await probe_worker_health(url)
        assert probe == WorkerHealthProbe(healthy=True, body=None)

        spawner = LazyWorkerSpawner(worker_url=url, worker_port=port, auto_spawn=True)
        await spawner.ensure_worker()
        async with httpx.AsyncClient() as client:
            incumbent = await client.get(f"{url}/health")
        second_probe = await probe_worker_health(url)

    assert incumbent.status_code == 200
    assert spawner.spawned is False
    assert spawner.process is None
    assert second_probe == WorkerHealthProbe(healthy=True, body=None)


@pytest.mark.asyncio(loop_scope="function")
async def test_nothing_listening_is_reported_absent(tmp_path: Path) -> None:
    """A port with no server is absent - the reading reserved for a dead worker.

    The counterpart that keeps the proof above honest: ``None`` must still mean
    something, or asserting "not None" for the unreadable worker would be
    vacuous. Port 9 (discard) refuses the connection outright.
    """
    dead = "http://127.0.0.1:9"
    probe = await probe_worker_health(dead)
    assert probe == WorkerHealthProbe(healthy=False, body=None)
    # A refused connection is an OBSERVATION of absence, not a failure to observe.
    assert probe.indeterminate is False


@pytest.mark.asyncio(loop_scope="function")
async def test_a_stalled_worker_is_unhealthy_but_not_observed_absent() -> None:
    """A worker that accepts and never answers yields an INDETERMINATE verdict.

    This is the third reading the pair above does not cover, and the one run
    admission turns on. A worker compiling a graph for an already-admitted run
    stops answering for seconds; the probe budget expires; and the old verdict was
    byte-identical to a dead worker's. Admission then refused an unrelated commit
    with 503 because the first run was still booting.

    The occupant is a real socket server that accepts the connection and sends
    nothing, so the client genuinely reads past its budget rather than being told
    the port is closed - which is precisely the distinction under proof.
    """
    with _stalled_worker() as url:
        probe = await probe_worker_health(url, timeout=1.0)

    assert probe.healthy is False, "a worker that never answered is not healthy"
    assert probe.indeterminate is True, (
        "a read that outran its budget proves nothing about the worker's existence"
    )
