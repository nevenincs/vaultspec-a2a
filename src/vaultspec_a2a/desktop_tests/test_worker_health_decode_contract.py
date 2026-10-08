"""Real-HTTP proof that one worker never gets two contradictory health verdicts.

A process that answers ``200`` with a body the decoder cannot read is the case
where the gateway's readers could disagree about the same occupant. One live
occupant must never read as simultaneously ready and absent, because the absent
reading is the one that spawns a competitor onto a port that process still
holds.

The occupant here is a real HTTP server in a real subprocess serving a real
malformed ``200`` over a real socket - the condition itself, not a stand-in for
any code under test. Every assertion drives production functions directly.

Three different questions are asked of that one occupant, and the answers must
be consistent:

- *is a ready worker there?* - no; a 200 is not a readiness answer, and an
  unreadable body carries no readiness fact at all;
- *does something hold this port?* - yes, and that is read from the SOCKET, not
  from the health body, which is why an unreadable occupant can be refused
  without being mistaken for a dead one;
- *may it be adopted or evicted?* - no; absence of pairing evidence is not
  evidence of ownership, under either profile, and the spawn is refused rather
  than attempted.

Keeping the second question on the socket is the load-bearing part. While it was
answered by the status code, a verdict change anywhere in the health rule could
turn a held port into an apparently free one.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import httpx
import pytest

from ..control._worker_health import WorkerHealthProbe, probe_worker_health
from ..control.worker_management import LazyWorkerSpawner
from ..testing import (
    WatchedProcess,
    await_ready,
    free_port,
    reap_process,
    settings_override,
)
from ..utils import ProcessContainment, spawn_contained
from ..utils._process_tree import PortClaim, classify_port_claim, port_has_listener

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
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
def _running_worker(
    command: list[str], *, name: str, ready: Callable[[], bool]
) -> Generator[None]:
    """Run *command* contained until *ready* passes, and reap its tree after."""
    containment = ProcessContainment.create()
    process = spawn_contained(
        command,
        containment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    worker = WatchedProcess(name, process, containment)
    try:
        await_ready(ready, what=name, watch=[worker], timeout=15.0, interval=0.05)
        yield
    finally:
        reap_process(worker)


@contextlib.contextmanager
def _stalled_worker() -> Generator[str]:
    """Run a real server that accepts /health and never sends a response."""
    port = free_port()
    with _running_worker(
        [sys.executable, "-c", _STALLED_WORKER, str(port)],
        name="stalled worker",
        ready=lambda: port_has_listener(port, timeout=1.0),
    ):
        yield f"http://127.0.0.1:{port}"


@contextlib.contextmanager
def _malformed_worker(tmp_path: Path) -> Generator[tuple[str, int]]:
    """Run a real HTTP server that answers /health 200 with undecodable bytes."""
    port = free_port()
    script = tmp_path / "malformed_worker.py"
    script.write_text(_MALFORMED_WORKER, encoding="utf-8")
    url = f"http://127.0.0.1:{port}"
    with _running_worker(
        [sys.executable, str(script), str(port)],
        name="malformed worker",
        ready=lambda: httpx.get(f"{url}/health", timeout=1.0).status_code == 200,
    ):
        yield url, port


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unreadable_occupant_is_not_ready_but_still_holds_the_port(
    tmp_path: Path,
) -> None:
    """One live unreadable occupant yields consistent, non-contradictory reads.

    Each assertion is a different production entry point against the SAME live
    occupant, which is what makes the set a split-brain proof rather than several
    unrelated checks.

    Load-bearing: the port claim distinguishes this held port from a free one
    even though the health verdict is now the same ``False`` a dead worker gives.
    Collapsing those two would let a spawn compete for a port a live process
    still holds - which is observable here as the worker stderr log the spawn
    path opens before it starts a process, and which must not appear.
    """
    with _malformed_worker(tmp_path) as (url, port):
        # Not a readiness answer: a 200 proves only that something answered, and
        # these bytes carry no readiness fact to read.
        probe = await probe_worker_health(url, internal_token=None)
        assert probe == WorkerHealthProbe(healthy=False, body=None)
        # ...yet the port is demonstrably held, from the socket rather than the
        # body, and held by this test's own descendant, so a credentialed read
        # of it would be authorized where a stranger's would not.
        assert classify_port_claim(port, os.getpid(), timeout=1.0) is PortClaim.OURS

        with settings_override(a2a_home=tmp_path / "home"):
            spawner = LazyWorkerSpawner(
                worker_url=url, worker_port=port, auto_spawn=True, internal_token=None
            )
            await spawner.ensure_worker()
            stderr_log = spawner.stderr_log_path
        async with httpx.AsyncClient() as client:
            incumbent = await client.get(f"{url}/health")
        second_probe = await probe_worker_health(url, internal_token=None)

    assert incumbent.status_code == 200
    assert spawner.spawned is False
    assert spawner.process is None
    assert stderr_log is not None
    assert stderr_log.exists() is False
    assert second_probe == WorkerHealthProbe(healthy=False, body=None)


@pytest.mark.asyncio(loop_scope="function")
async def test_nothing_listening_is_reported_absent(tmp_path: Path) -> None:
    """A port with no server is absent - the reading reserved for a dead worker.

    The counterpart that keeps the proof above honest: ``None`` must still mean
    something, or asserting "not None" for the unreadable worker would be
    vacuous. Port 9 (discard) refuses the connection outright.
    """
    dead = "http://127.0.0.1:9"
    probe = await probe_worker_health(dead, internal_token=None)
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
        probe = await probe_worker_health(url, timeout=1.0, internal_token=None)

    assert probe.healthy is False, "a worker that never answered is not healthy"
    assert probe.indeterminate is True, (
        "a read that outran its budget proves nothing about the worker's existence"
    )
